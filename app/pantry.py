"""보유 재료 기반 추천 + 저장된 재료(자주 쓰는 재료를 저장해 두고 매번 자동으로 함께 쓰기).

1) 후보 찾기(일반 코드): 보유 재료와 이름이 같은 재료가 있는 레시피를 '가진 재료 비율이 높은 순'으로 고른다.
2) 맞춤 조정(AI): 사용자가 후보 하나를 고르면 Gemini 가 대체 재료와 바뀐 조리법을 제안한다.
"""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from . import ai
from .extensions import db
from .models import Ingredient, PantryItem, Recipe
from .recipe_util import ALIASES, BASIC_SEASONINGS, BASIC_TO_SAVE, COMMON_INGREDIENTS, normalize_name
from .services import ai_error_message, ai_rate_limited, new_draft, source_info, visible_recipe_or_404

bp = Blueprint("pantry", __name__)

MAX_HAVE = 30
MAX_CANDIDATES = 6
MAX_SAVED = 60


def _have_list(values):
    """?have=달걀&have=대파 + (자바스크립트가 꺼진 경우) add=쉼표로 구분한 재료 → 중복 없는 목록"""
    raw = values.getlist("have") + [x for x in values.get("add", "").replace("、", ",").split(",")]
    out, seen = [], set()
    for name in raw:
        name = " ".join(name.split())[:40]
        key = normalize_name(name)
        if name and key not in seen:
            seen.add(key)
            out.append(ALIASES.get(name.replace(" ", ""), name))
    return out[:MAX_HAVE]


def _saved_items():
    """로그인한 사용자가 저장해 둔 재료 (로그인 안 했으면 빈 목록)"""
    if not current_user.is_authenticated:
        return []
    return db.session.scalars(db.select(PantryItem).where(PantryItem.user_id == current_user.id)
                              .order_by(PantryItem.created_at, PantryItem.id)).all()


def _split_saved(have, saved_names):
    """이번에 넣은 재료 중 이미 저장된 것은 빼고, 빠진 이름을 돌려준다 (같은 재료를 두 번 세지 않게)"""
    saved_keys = {normalize_name(n) for n in saved_names}
    today = [h for h in have if normalize_name(h) not in saved_keys]
    dup = [h for h in have if normalize_name(h) in saved_keys]
    return today, dup


def find_candidates(have, saved=()):
    """보유 재료(이번에 넣은 재료 + 저장된 재료)와 이름이 일치하는 재료가 있는 레시피 (AI 사용 안 함).

    - 소금·간장 같은 기본 양념은 순위 계산에서 아예 뺀다 (가진 것도, 부족한 것도 아님). '기본 양념' 줄에 따로 보여 준다
      → 기본 양념을 저장해 두어도 양념이 많은 레시피가 괜히 앞으로 오지 않는다
    - 순서: 가진 재료 비율이 높은 순 → 부족한 재료가 적은 순 → 가진 재료가 많은 순 → 최근 레시피 순
      비율 = 가진 재료 수 ÷ (가진 재료 수 + 부족한 재료 수)
    - 저장된 재료로 맞춘 재료는 따로 표시한다 (저장해 두고 다 쓴 재료일 수 있어 확인하라는 뜻. 순위에는 영향 없음)
    직접 작성한 레시피와 공공 레시피가 후보다. 공공 레시피가 1,000개가 넘으므로 레시피마다 재료를 따로 읽지 않고
    (레시피 번호, 재료 이름)을 한 번에 읽어 계산한 뒤, 고른 레시피만 불러온다.
    """
    today_keys = {normalize_name(h) for h in have}
    saved_keys = {normalize_name(h) for h in saved} - today_keys
    owned = today_keys | saved_keys
    basic_owned = owned | {"물"}  # 물은 언제나 있다고 본다
    if not owned - BASIC_SEASONINGS:
        return []
    visible = Recipe.is_public.is_(True)
    if current_user.is_authenticated:
        visible = or_(visible, Recipe.author_id == current_user.id)
    rows = db.session.execute(
        db.select(Ingredient.recipe_id, Ingredient.name).join(Recipe, Recipe.id == Ingredient.recipe_id)
        .where(visible, Recipe.origin.in_(("user", "public")))
    ).all()
    by_recipe = {}
    for recipe_id, name in rows:
        has, missing = by_recipe.setdefault(recipe_id, (set(), set()))
        key = normalize_name(name)
        if key in BASIC_SEASONINGS:
            continue
        (has if key in owned else missing).add(key)

    def rank(rid):
        has, missing = by_recipe[rid]
        return (-len(has) / (len(has) + len(missing)), len(missing), -len(has), -rid)

    ranked = sorted((rid for rid, (has, _) in by_recipe.items() if has), key=rank)[:MAX_CANDIDATES]
    recipes = {r.id: r for r in db.session.scalars(db.select(Recipe).where(Recipe.id.in_(ranked)))} if ranked else {}
    out = []
    for rid in ranked:
        r = recipes[rid]
        c = {"r": r, "has": [], "has_saved": [], "missing": [], "basic": []}
        for i in r.ingredients:
            key = normalize_name(i.name)
            if key in BASIC_SEASONINGS:
                c["basic"].append({"i": i, "owned": key in basic_owned})
            elif key in today_keys:
                c["has"].append(i)
            elif key in saved_keys:
                c["has_saved"].append(i)
            else:
                c["missing"].append(i)
        has, missing = by_recipe[rid]
        c["has_count"], c["total"] = len(has), len(has) + len(missing)
        c["percent"] = round(100 * len(has) / (len(has) + len(missing)))
        out.append(c)
    return out


@bp.route("/pantry")
def index():
    saved = _saved_items()
    saved_names = [p.name for p in saved]
    have, dup = _split_saved(_have_list(request.args), saved_names)
    for name in dup:
        flash(f"‘{name}’은(는) 저장된 재료에 이미 있어요. 후보를 찾을 때 자동으로 함께 써요. "
              "다 떨어졌다면 저장된 재료에서 지워 주세요.", "warning")
    searched = bool(have) or (request.args.get("find") == "1" and bool(saved))
    candidates = find_candidates(have, saved_names) if searched else []
    return render_template("pantry/index.html", have=have, saved=saved, candidates=candidates, searched=searched,
                           basic_to_save=[b for b in BASIC_TO_SAVE if normalize_name(b) not in {normalize_name(n) for n in saved_names}])


@bp.post("/pantry/adapt")
@login_required
def adapt():
    saved_names = [p.name for p in _saved_items()]
    have, _ = _split_saved(_have_list(request.form), saved_names)
    recipe = visible_recipe_or_404(request.form.get("recipe_id", type=int) or 0)
    back = url_for("pantry.index", have=have, find=1)
    all_have = have + saved_names  # AI 에는 저장된 재료까지 '가진 재료'로 알려 준다
    if not all_have:
        flash("보유 재료를 한 개 이상 넣어 주세요.", "danger")
        return redirect(back)
    if ai_rate_limited():
        flash("AI를 너무 자주 불렀어요. 1분 뒤에 다시 시도해 주세요.", "warning")
        return redirect(back)
    owned = {normalize_name(h) for h in all_have}
    missing = [{"이름": i.name, "수량": i.quantity, "단위": i.unit} for i in recipe.ingredients if normalize_name(i.name) not in owned]
    try:
        result = ai.adapt_recipe(recipe, all_have, missing)
    except ai.AIUnavailable as e:
        flash(ai_error_message(e), "danger")
        return redirect(back)
    draft = new_draft("ai_pantry", result, [source_info(recipe)], "보유 재료: " + ", ".join(all_have))
    return redirect(url_for("mix.draft", draft_id=draft.id))


# ---------- 저장된 재료 ----------
def _back_to_pantry():
    """저장·삭제 뒤에는 보던 화면(이번에 넣은 재료 포함)으로 돌아간다"""
    return redirect(url_for("pantry.index", have=request.form.getlist("keep"), find=request.form.get("find") or None))


def _save_names(names):
    existing = {normalize_name(p.name) for p in _saved_items()}
    added, already = [], []
    for name in names:
        key = normalize_name(name)
        if key in existing:
            already.append(name)
            continue
        if len(existing) >= MAX_SAVED:
            flash(f"재료는 {MAX_SAVED}개까지 저장할 수 있어요. 안 쓰는 재료를 지운 뒤 다시 저장해 주세요.", "warning")
            break
        db.session.add(PantryItem(user_id=current_user.id, name=name))
        existing.add(key)
        added.append(name)
    db.session.commit()
    if added:
        flash("저장했어요: " + ", ".join(added), "success")
    if already:
        flash("이미 저장된 재료예요: " + ", ".join(already), "info")
    if not added and not already:
        flash("저장할 재료 이름을 입력해 주세요.", "danger")


@bp.post("/pantry/saved")
@login_required
def save_items():
    _save_names(_have_list(request.form))
    return _back_to_pantry()


@bp.post("/pantry/saved/basics")
@login_required
def save_basics():
    _save_names(list(BASIC_TO_SAVE))
    return _back_to_pantry()


@bp.post("/pantry/saved/<int:item_id>/delete")
@login_required
def delete_item(item_id):
    item = db.session.get(PantryItem, item_id)
    if item is None or item.user_id != current_user.id:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    flash(f"‘{item.name}’을(를) 저장된 재료에서 지웠어요.", "success")
    return _back_to_pantry()


@bp.route("/api/ingredients")
def suggest():
    """재료 이름 자동완성: 기본 재료 목록 + 등록된 레시피의 재료명 + 다른 이름(계란→달걀)."""
    q = " ".join(request.args.get("q", "").split())[:20]
    if not q:
        return jsonify([])
    key = normalize_name(q)
    names = set(COMMON_INGREDIENTS)
    names.update(n for n in db.session.scalars(
        db.select(Ingredient.name).join(Recipe, Recipe.id == Ingredient.recipe_id)
        .where(Recipe.is_public.is_(True), Ingredient.name.ilike(f"%{q[:1]}%")).distinct().limit(300)) if len(n) <= 20)
    out = []
    for name in names:
        alias = next((a for a, target in ALIASES.items() if target == name and q in a), None)
        if key in normalize_name(name) or q.replace(" ", "") in name.replace(" ", "") or alias:
            out.append({"name": name, "alias": alias})
    out.sort(key=lambda o: (not o["name"].startswith(q), len(o["name"]), o["name"]))
    return jsonify(out[:8])
