"""레시피 등록 · 수정 · 삭제 · 상세 · 좋아요 · 즐겨찾기 · 공개 전환"""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .auth import _safe_next
from .extensions import db
from .models import CATEGORIES, AIDraft, Bookmark, Like, Recipe
from .recipe_util import parse_recipe_form
from .services import apply_recipe_data, card_context, own_recipe_or_403, save_draft_as_recipe, toggle, visible_recipe_or_404

bp = Blueprint("recipes", __name__, url_prefix="/recipes")


def _form_from_recipe(r):
    """레시피(또는 AI 결과) → 등록 폼에 채울 값"""
    return {"title": r["title"], "description": r.get("description", ""), "category": r.get("category", "기타"),
            "servings": r["servings"], "cook_time_min": r["cook_time_min"], "ingredients": r["ingredients"],
            "steps": r["steps"], "is_public": r.get("is_public", True)}


def _recipe_dict(r):
    return {"title": r.title, "description": r.description, "category": r.category, "servings": r.servings,
            "cook_time_min": r.cook_time_min, "is_public": r.is_public, "steps": [s.content for s in r.steps],
            "ingredients": [{"name": i.name, "quantity": i.quantity, "unit": i.unit} for i in r.ingredients]}


def _my_draft_or_404(draft_id):
    draft = db.session.get(AIDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        abort(404)
    return draft


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    # AI 결과를 '수정 후 저장'하는 경우: draft 의 내용을 폼에 채워 보여 주고, 저장할 때 출처를 함께 기록한다
    draft_id = request.values.get("draft", type=int)
    draft = _my_draft_or_404(draft_id) if draft_id else None
    if draft and draft.saved_recipe_id and db.session.get(Recipe, draft.saved_recipe_id):
        flash("이 AI 결과는 이미 저장했어요.", "info")
        return redirect(url_for("recipes.detail", recipe_id=draft.saved_recipe_id))
    if request.method == "POST":
        data, errors = parse_recipe_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("recipes/form.html", values=data, draft=draft, mode="new", categories=CATEGORIES), 400
        if draft:
            recipe = save_draft_as_recipe(draft, data)
            flash("AI 레시피를 내 레시피로 저장했어요. 원본 출처가 함께 표시돼요.", "success")
        else:
            recipe = apply_recipe_data(Recipe(author_id=current_user.id, origin="user"), data)
            db.session.add(recipe)
            db.session.commit()
            flash("레시피를 등록했어요.", "success")
        return redirect(url_for("recipes.detail", recipe_id=recipe.id))

    if draft:
        ai = draft.data
        values = _form_from_recipe({**ai, "description": ai.get("summary", ""), "is_public": False,
                                    "category": (draft.source_list or [{}])[0].get("category", "기타")})
    else:
        values = {"servings": 2, "cook_time_min": 20, "category": CATEGORIES[0], "is_public": True,
                  "ingredients": [], "steps": []}
    return render_template("recipes/form.html", values=values, draft=draft, mode="new", categories=CATEGORIES)


@bp.route("/<int:recipe_id>")
def detail(recipe_id):
    r = visible_recipe_or_404(recipe_id)
    ctx = card_context([r])
    return render_template("recipes/detail.html", r=r, like_count=ctx["likes"].get(r.id, 0),
                           liked=r.id in ctx["liked"], marked=r.id in ctx["marked"],
                           is_owner=current_user.is_authenticated and r.author_id == current_user.id)


@bp.route("/<int:recipe_id>/edit", methods=["GET", "POST"])
@login_required
def edit(recipe_id):
    r = own_recipe_or_403(recipe_id)
    if request.method == "POST":
        data, errors = parse_recipe_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("recipes/form.html", values=data, recipe=r, mode="edit", categories=CATEGORIES), 400
        apply_recipe_data(r, data)
        db.session.commit()
        flash("수정 내용을 저장했어요.", "success")
        return redirect(url_for("recipes.detail", recipe_id=r.id))
    return render_template("recipes/form.html", values=_recipe_dict(r), recipe=r, mode="edit", categories=CATEGORIES)


@bp.post("/<int:recipe_id>/delete")
@login_required
def delete(recipe_id):
    r = own_recipe_or_403(recipe_id)
    title = r.title
    db.session.delete(r)
    db.session.commit()
    flash(f"‘{title}’ 레시피를 삭제했어요.", "info")
    return redirect(url_for("main.mypage"))


@bp.post("/<int:recipe_id>/visibility")
@login_required
def visibility(recipe_id):
    r = own_recipe_or_403(recipe_id)
    r.is_public = not r.is_public
    db.session.commit()
    flash("커뮤니티에 공개했어요." if r.is_public else "나만 보기로 바꿨어요.", "success")
    return redirect(url_for("recipes.detail", recipe_id=r.id))


def _toggle_response(model, recipe_id, on_text, off_text):
    r = visible_recipe_or_404(recipe_id)
    on = toggle(model, r.id)
    if request.accept_mimetypes.best == "application/json":  # 화면을 다시 불러오지 않는 요청 (app.js)
        count = db.session.scalar(db.select(db.func.count()).select_from(model).where(model.recipe_id == r.id))
        return jsonify(on=on, count=count, message=on_text if on else off_text)
    flash(on_text if on else off_text, "success")
    return redirect(_safe_next(request.form.get("next")) or url_for("recipes.detail", recipe_id=r.id))


@bp.post("/<int:recipe_id>/like")
@login_required
def like(recipe_id):
    return _toggle_response(Like, recipe_id, "좋아요를 눌렀어요.", "좋아요를 취소했어요.")


@bp.post("/<int:recipe_id>/bookmark")
@login_required
def bookmark(recipe_id):
    return _toggle_response(Bookmark, recipe_id, "즐겨찾기에 추가했어요.", "즐겨찾기에서 뺐어요.")


@bp.route("/<int:recipe_id>/compare")
def compare(recipe_id):
    """저장된 AI 조합 레시피의 '원본과 비교'"""
    r = visible_recipe_or_404(recipe_id)
    info = r.ai_info
    if r.origin != "ai_mix" or not info.get("changes"):
        abort(404)
    sources = [{"id": s.source_recipe_id, "title": s.source_title, "author": s.source_author} for s in r.sources]
    result = {"title": r.title, "servings": r.servings, "cook_time_min": r.cook_time_min}
    return render_template("ai/compare.html", changes=info["changes"], sources=sources, result=result,
                           back_url=url_for("recipes.detail", recipe_id=r.id), back_label="레시피로 돌아가기", draft=None)
