"""메인(레시피 둘러보기) · 마이페이지"""
from flask import Blueprint, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from .extensions import db
from .models import CATEGORIES, Bookmark, Ingredient, Like, Recipe
from .services import card_context

bp = Blueprint("main", __name__)

PER_PAGE = 12
TIME_FILTERS = {0: "시간 제한 없음", 15: "15분 이하", 30: "30분 이하", 60: "1시간 이하"}
ORIGIN_FILTERS = {"all": "모든 레시피", "user": "직접 작성", "ai": "AI로 만든 레시피"}


def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()[:40]
    category = request.args.get("category", "전체")
    if category not in CATEGORIES:
        category = "전체"
    max_time = request.args.get("time", 0, type=int)
    if max_time not in TIME_FILTERS:
        max_time = 0
    origin = request.args.get("origin", "all")
    if origin not in ORIGIN_FILTERS:
        origin = "all"
    sort = "popular" if request.args.get("sort") == "popular" else "latest"

    stmt = db.select(Recipe).where(Recipe.is_public.is_(True))
    if category != "전체":
        stmt = stmt.where(Recipe.category == category)
    if max_time:
        stmt = stmt.where(Recipe.cook_time_min <= max_time)
    if origin == "user":
        stmt = stmt.where(Recipe.origin == "user")
    elif origin == "ai":
        stmt = stmt.where(Recipe.origin != "user")
    if q:
        like = f"%{_escape_like(q)}%"
        by_ingredient = db.select(Ingredient.recipe_id).where(Ingredient.name.ilike(like, escape="\\"))
        stmt = stmt.where(or_(Recipe.title.ilike(like, escape="\\"), Recipe.id.in_(by_ingredient)))
    if sort == "popular":
        # 인기순은 좋아요 수 기준으로 계산한다 (AI 사용 안 함)
        like_count = db.select(func.count(Like.user_id)).where(Like.recipe_id == Recipe.id).correlate(Recipe).scalar_subquery()
        stmt = stmt.order_by(like_count.desc(), Recipe.created_at.desc())
    else:
        stmt = stmt.order_by(Recipe.created_at.desc(), Recipe.id.desc())

    page = db.paginate(stmt, page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False)
    filters = {"q": q, "category": category, "time": max_time, "origin": origin, "sort": sort}
    return render_template("index.html", page=page, recipes=page.items, filters=filters,
                           categories=CATEGORIES, time_filters=TIME_FILTERS, origin_filters=ORIGIN_FILTERS,
                           filtered=bool(q or category != "전체" or max_time or origin != "all"),
                           **card_context(page.items))


@bp.route("/me")
@login_required
def mypage():
    tab = request.args.get("tab", "user")
    if tab not in ("user", "ai", "favorites"):
        tab = "user"
    mine = [r for r in current_user.recipes if not r.is_ai]
    ai_made = [r for r in current_user.recipes if r.is_ai]
    favorites = db.session.scalars(
        db.select(Recipe).join(Bookmark, Bookmark.recipe_id == Recipe.id)
        .where(Bookmark.user_id == current_user.id, or_(Recipe.is_public.is_(True), Recipe.author_id == current_user.id))
        .order_by(Bookmark.created_at.desc())
    ).all()
    shown = {"user": mine, "ai": ai_made, "favorites": favorites}[tab]
    return render_template("mypage.html", tab=tab, shown=shown, counts={"user": len(mine), "ai": len(ai_made), "favorites": len(favorites)},
                           **card_context(shown))
