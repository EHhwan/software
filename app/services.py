"""여러 화면이 함께 쓰는 로직: 권한 확인, 좋아요·즐겨찾기 집계, 레시피 저장, AI 호출 제한."""
import json
from datetime import timedelta

from flask import abort
from flask_login import current_user
from sqlalchemy import func

from .extensions import db
from .models import AICall, AIDraft, Bookmark, Ingredient, Like, Recipe, RecipeSource, Step, utcnow

AI_LIMIT = 6         # 한 사람이
AI_WINDOW_SEC = 60   # 1분에 이 횟수까지만 AI 를 부를 수 있다 (무료 사용량 보호)


def visible_recipe_or_404(recipe_id):
    """공개 레시피이거나 내 레시피면 돌려주고, 아니면 404 (비공개 레시피가 있다는 사실도 숨긴다)."""
    r = db.session.get(Recipe, recipe_id)
    if r is None or not (r.is_public or (current_user.is_authenticated and r.author_id == current_user.id)):
        abort(404)
    return r


def own_recipe_or_403(recipe_id):
    r = visible_recipe_or_404(recipe_id)
    if not current_user.is_authenticated or r.author_id != current_user.id:
        abort(403)
    return r


def like_counts(recipe_ids):
    if not recipe_ids:
        return {}
    rows = db.session.execute(
        db.select(Like.recipe_id, func.count()).where(Like.recipe_id.in_(recipe_ids)).group_by(Like.recipe_id)
    ).all()
    return dict(rows)


def user_flags(recipe_ids):
    """현재 사용자가 좋아요·즐겨찾기한 레시피 id 집합."""
    if not current_user.is_authenticated or not recipe_ids:
        return set(), set()
    liked = set(db.session.scalars(db.select(Like.recipe_id).where(
        Like.user_id == current_user.id, Like.recipe_id.in_(recipe_ids))))
    marked = set(db.session.scalars(db.select(Bookmark.recipe_id).where(
        Bookmark.user_id == current_user.id, Bookmark.recipe_id.in_(recipe_ids))))
    return liked, marked


def card_context(recipes):
    """레시피 카드 목록에 필요한 좋아요 수·내 좋아요·내 즐겨찾기."""
    ids = [r.id for r in recipes]
    liked, marked = user_flags(ids)
    return {"likes": like_counts(ids), "liked": liked, "marked": marked}


def toggle(model, recipe_id):
    """좋아요·즐겨찾기 켜기/끄기. (사용자, 레시피)가 기본키라 같은 사람은 한 번만 들어간다."""
    row = db.session.get(model, (current_user.id, recipe_id))
    if row:
        db.session.delete(row)
        on = False
    else:
        db.session.add(model(user_id=current_user.id, recipe_id=recipe_id))
        on = True
    db.session.commit()
    return on


def apply_recipe_data(recipe, data):
    """검증을 통과한 폼·AI 데이터로 레시피 내용을 채운다 (재료·순서는 통째로 교체)."""
    recipe.title = data["title"]
    recipe.description = data.get("description", "")
    recipe.category = data.get("category") or recipe.category or "기타"
    recipe.servings = data["servings"]
    recipe.cook_time_min = data["cook_time_min"]
    if "is_public" in data:
        recipe.is_public = data["is_public"]
    if recipe.id is not None:
        # 수정할 때: 예전 재료·단계를 먼저 지워야 '1단계'가 두 개가 되는 충돌(고유 번호 제약)이 나지 않는다
        recipe.ingredients.clear()
        recipe.steps.clear()
        db.session.flush()
    recipe.ingredients = [Ingredient(position=i + 1, name=x["name"], quantity=x["quantity"], unit=x["unit"])
                          for i, x in enumerate(data["ingredients"])]
    recipe.steps = [Step(number=i + 1, content=s) for i, s in enumerate(data["steps"])]
    return recipe


def save_draft_as_recipe(draft, data=None):
    """AI 결과를 내 레시피로 저장. 처음에는 '나만 보기'로 저장하고, 원본 출처를 함께 기록한다.
    data 를 주면(사용자가 수정한 내용) 그 내용으로, 없으면 AI 결과 그대로 저장한다."""
    ai = draft.data
    if data is None:
        data = {"title": ai["title"], "description": ai.get("summary", ""), "servings": ai["servings"],
                "cook_time_min": ai["cook_time_min"], "ingredients": ai["ingredients"], "steps": ai["steps"],
                "category": draft.source_list[0].get("category") if draft.source_list else "기타", "is_public": False}
    recipe = Recipe(author_id=draft.user_id, origin=draft.kind, is_public=False)
    apply_recipe_data(recipe, data)
    note = {k: ai.get(k) for k in ("summary", "changes", "notes", "reason", "substitutions", "still_needed") if ai.get(k)}
    note["goal"] = draft.goal
    recipe.ai_note = json.dumps(note, ensure_ascii=False)
    recipe.sources = [
        RecipeSource(position=i + 1, source_recipe_id=s["id"] if db.session.get(Recipe, s["id"]) else None,
                     source_title=s["title"][:60], source_author=s["author"][:12])
        for i, s in enumerate(draft.source_list)
    ]
    db.session.add(recipe)
    db.session.flush()
    draft.saved_recipe_id = recipe.id
    db.session.commit()
    return recipe


def ai_rate_limited():
    """1분 안에 AI_LIMIT 번 넘게 부르면 True. 아니면 이번 호출을 기록하고 False."""
    since = utcnow() - timedelta(seconds=AI_WINDOW_SEC)
    used = db.session.scalar(db.select(func.count(AICall.id)).where(AICall.user_id == current_user.id, AICall.at >= since))
    if used >= AI_LIMIT:
        return True
    db.session.add(AICall(user_id=current_user.id))
    db.session.commit()
    return False


def ai_error_message(err):
    text = str(err).lower()
    if "429" in text or "quota" in text or "exhausted" in text or "rate limit" in text:
        return "AI 사용량 한도에 걸렸어요. 잠시 뒤 다시 시도해 주세요."
    if "api_key" in text or "api key" in text:
        return "AI 연결 설정(API 키)에 문제가 있어요. 관리자에게 알려 주세요."
    if "json" in text or "형식" in text or "없어요" in text or "비었" in text:
        return "AI 답의 형식이 올바르지 않아 보여 드릴 수 없어요. 다시 시도해 주세요."
    return "AI가 지금 응답하지 않아요. 잠시 뒤 다시 시도해 주세요."


def new_draft(kind, payload, sources, goal):
    draft = AIDraft(user_id=current_user.id, kind=kind, payload=json.dumps(payload, ensure_ascii=False),
                    sources=json.dumps(sources, ensure_ascii=False), goal=goal)
    db.session.add(draft)
    db.session.commit()
    return draft


def source_info(recipe):
    return {"id": recipe.id, "title": recipe.title, "author": recipe.author.nickname, "category": recipe.category,
            "servings": recipe.servings, "cook_time_min": recipe.cook_time_min}
