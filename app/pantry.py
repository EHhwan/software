"""보유 재료 기반 추천.

1) 후보 찾기(일반 코드): 보유 재료와 이름이 같은 재료가 있는 레시피를 '부족한 재료가 적은 순'으로 고른다.
2) 맞춤 조정(AI): 사용자가 후보 하나를 고르면 Gemini 가 대체 재료와 바뀐 조리법을 제안한다.
"""
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from . import ai
from .extensions import db
from .models import Ingredient, Recipe
from .recipe_util import ALIASES, BASIC_SEASONINGS, COMMON_INGREDIENTS, normalize_name
from .services import ai_error_message, ai_rate_limited, new_draft, source_info, visible_recipe_or_404

bp = Blueprint("pantry", __name__)

MAX_HAVE = 30
MAX_CANDIDATES = 6


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


def find_candidates(have):
    """보유 재료와 이름이 일치하는 재료가 있는 레시피 (AI 사용 안 함).

    - 소금·간장 같은 기본 양념은 가지고 있지 않아도 '부족한 재료'로 세지 않는다 (따로 '기본 양념'으로 보여 줌)
    - 순서: 가진 재료 비율이 높은 순 → 부족한 재료가 적은 순 → 가진 재료가 많은 순 → 최근 레시피 순
      비율 = 가진 재료 수 ÷ (가진 재료 수 + 부족한 재료 수). 재료가 적은 레시피가 가진 것 하나로 앞에 오는 일을 막는다.
    직접 작성한 레시피와 공공 레시피가 후보다. 공공 레시피가 1,000개가 넘으므로 레시피마다 재료를 따로 읽지 않고
    (레시피 번호, 재료 이름)을 한 번에 읽어 계산한 뒤, 고른 레시피만 불러온다.
    """
    owned = {normalize_name(h) for h in have}
    if not owned:
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
        if key in owned:
            has.add(key)
        elif key not in BASIC_SEASONINGS:
            missing.add(key)

    def rank(rid):
        has, missing = by_recipe[rid]
        return (-len(has) / (len(has) + len(missing)), len(missing), -len(has), -rid)

    ranked = sorted((rid for rid, (has, _) in by_recipe.items() if has), key=rank)[:MAX_CANDIDATES]
    recipes = {r.id: r for r in db.session.scalars(db.select(Recipe).where(Recipe.id.in_(ranked)))} if ranked else {}
    out = []
    for rid in ranked:
        r = recipes[rid]
        c = {"r": r, "has": [], "missing": [], "basic": []}
        for i in r.ingredients:
            key = normalize_name(i.name)
            c["has" if key in owned else "basic" if key in BASIC_SEASONINGS else "missing"].append(i)
        c["percent"] = round(100 * len(by_recipe[rid][0]) / (len(by_recipe[rid][0]) + len(by_recipe[rid][1])))
        out.append(c)
    return out


@bp.route("/pantry")
def index():
    have = _have_list(request.args)
    return render_template("pantry/index.html", have=have, candidates=find_candidates(have), searched=bool(have))


@bp.post("/pantry/adapt")
@login_required
def adapt():
    have = _have_list(request.form)
    recipe = visible_recipe_or_404(request.form.get("recipe_id", type=int) or 0)
    back = url_for("pantry.index", have=have)
    if not have:
        flash("보유 재료를 한 개 이상 넣어 주세요.", "danger")
        return redirect(back)
    if ai_rate_limited():
        flash("AI를 너무 자주 불렀어요. 1분 뒤에 다시 시도해 주세요.", "warning")
        return redirect(back)
    owned = {normalize_name(h) for h in have}
    missing = [{"이름": i.name, "수량": i.quantity, "단위": i.unit} for i in recipe.ingredients if normalize_name(i.name) not in owned]
    try:
        result = ai.adapt_recipe(recipe, have, missing)
    except ai.AIUnavailable as e:
        flash(ai_error_message(e), "danger")
        return redirect(back)
    draft = new_draft("ai_pantry", result, [source_info(recipe)], "보유 재료: " + ", ".join(have))
    return redirect(url_for("mix.draft", draft_id=draft.id))


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
