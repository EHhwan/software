"""AI 레시피 믹스 + AI 결과 미리보기·비교·저장 (보유 재료 추천 결과도 같은 미리보기 화면을 쓴다)"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import ai
from .extensions import db
from .models import AIDraft, Recipe
from .services import (ai_error_message, ai_rate_limited, new_draft, save_draft_as_recipe, source_info)

bp = Blueprint("mix", __name__)

MAX_MIX_SERVINGS = 10
GOAL_EXAMPLES = [
    ("부드러운 맛", "자극적인 맛은 줄이고, 부드럽고 순한 맛으로 만들어 주세요."),
    ("간단한 조리", "조리 단계를 줄여 20분 안에 만들 수 있게 해 주세요."),
    ("두 요리의 특징 살리기", "두 레시피의 대표 재료와 맛이 한 요리에서 함께 느껴지게 해 주세요."),
    ("한 그릇 요리", "반찬 없이 한 그릇으로 먹을 수 있는 요리로 만들어 주세요."),
]


def _mix_candidates():
    own = db.session.scalars(db.select(Recipe).where(Recipe.author_id == current_user.id)
                             .order_by(Recipe.created_at.desc())).all()
    others = db.session.scalars(db.select(Recipe).where(Recipe.is_public.is_(True), Recipe.author_id != current_user.id)
                                .order_by(Recipe.created_at.desc()).limit(200)).all()
    return own, others


def _pick(candidates, recipe_id):
    by_id = {r.id: r for r in candidates}
    return by_id.get(recipe_id) or (candidates[0] if candidates else None)


@bp.route("/mix", methods=["GET", "POST"])
@login_required
def index():
    own_list, other_list = _mix_candidates()
    values = request.values
    own = _pick(own_list, values.get("own", type=int))
    other = _pick(other_list, values.get("other", type=int))
    goal = values.get("goal", "").strip()[:300]
    servings = min(MAX_MIX_SERVINGS, max(1, values.get("servings", type=int) or (own.servings if own else 2)))
    ctx = dict(own=own, other=other, own_list=own_list, other_list=other_list, goal=goal, servings=servings,
               max_servings=MAX_MIX_SERVINGS, goal_examples=GOAL_EXAMPLES)

    if request.method == "POST":
        # 화면에서 고른 id 가 내 레시피·다른 사람의 공개 레시피가 맞는지 서버에서 다시 확인한다
        if not own or own.id != values.get("own", type=int) or not other or other.id != values.get("other", type=int):
            flash("조합할 레시피를 다시 골라 주세요.", "danger")
            return render_template("mix/index.html", **ctx), 400
        if ai_rate_limited():
            flash("AI를 너무 자주 불렀어요. 1분 뒤에 다시 시도해 주세요.", "warning")
            return render_template("mix/index.html", **ctx), 429
        try:
            result = ai.mix_recipes(own, other, goal, servings)
        except ai.AIUnavailable as e:
            flash(ai_error_message(e), "danger")
            return render_template("mix/index.html", **ctx), 503
        draft = new_draft("ai_mix", result, [source_info(own), source_info(other)], goal)
        return redirect(url_for("mix.draft", draft_id=draft.id))
    return render_template("mix/index.html", **ctx)


def _my_draft_or_404(draft_id):
    d = db.session.get(AIDraft, draft_id)
    if d is None or d.user_id != current_user.id:
        abort(404)
    return d


@bp.route("/ai/drafts/<int:draft_id>")
@login_required
def draft(draft_id):
    d = _my_draft_or_404(draft_id)
    return render_template("ai/draft.html", d=d, data=d.data, sources=d.source_list)


@bp.route("/ai/drafts/<int:draft_id>/compare")
@login_required
def draft_compare(draft_id):
    d = _my_draft_or_404(draft_id)
    if d.kind != "ai_mix":
        abort(404)
    data = d.data
    return render_template("ai/compare.html", changes=data.get("changes", []), sources=d.source_list, result=data,
                           back_url=url_for("mix.draft", draft_id=d.id), back_label="결과로 돌아가기", draft=d)


@bp.post("/ai/drafts/<int:draft_id>/save")
@login_required
def draft_save(draft_id):
    d = _my_draft_or_404(draft_id)
    if d.saved_recipe_id and db.session.get(Recipe, d.saved_recipe_id):
        flash("이 AI 결과는 이미 저장했어요.", "info")
        return redirect(url_for("recipes.detail", recipe_id=d.saved_recipe_id))
    recipe = save_draft_as_recipe(d)
    flash("나만 보기로 저장했어요. 확인한 뒤 커뮤니티에 공개할 수 있어요.", "success")
    return redirect(url_for("recipes.detail", recipe_id=recipe.id))
