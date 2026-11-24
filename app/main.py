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
# 둘러보기는 두 칸으로 나눈다: 회원이 올린 레시피(직접 작성 + AI) / 공공 레시피(식품의약품안전처, 1,000개 이상)
# 한 목록에 섞으면 공공 레시피가 페이지 대부분을 차지해 커뮤니티 레시피가 묻히기 때문이다.
SOURCES = {"community": "커뮤니티 레시피", "public": "공공 레시피"}


def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _no_space(text):
    return "".join(text.split())


def _squeeze(column):
    """DB 쪽 글자에서 공백을 지운 값 (SQLite·PostgreSQL 모두 replace 함수가 있다)"""
    return func.replace(column, " ", "")


def _browse_query(source, q, category, max_time, origin):
    stmt = db.select(Recipe).where(Recipe.is_public.is_(True))
    stmt = stmt.where(Recipe.origin == "public") if source == "public" else stmt.where(Recipe.origin != "public")
    if category != "전체":
        stmt = stmt.where(Recipe.category == category)
    if max_time:
        stmt = stmt.where(Recipe.cook_time_min > 0, Recipe.cook_time_min <= max_time)  # 0 = 시간 정보 없음
    if origin == "user":
        stmt = stmt.where(Recipe.origin == "user")
    elif origin == "ai":
        stmt = stmt.where(Recipe.origin.in_(Recipe.AI_ORIGINS))
    if q:
        # 띄어쓰기를 무시하고 비교한다: '새우두부계란찜' 으로도 '새우 두부 계란찜' 을 찾고, 그 반대도 된다
        like = f"%{_escape_like(_no_space(q))}%"
        by_ingredient = db.select(Ingredient.recipe_id).where(_squeeze(Ingredient.name).ilike(like, escape="\\"))
        stmt = stmt.where(or_(_squeeze(Recipe.title).ilike(like, escape="\\"), Recipe.id.in_(by_ingredient)))
    return stmt


def _count(stmt):
    return db.session.scalar(db.select(func.count()).select_from(stmt.subquery()))


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()[:40]
    category = request.args.get("category", "전체")
    if category not in CATEGORIES:
        category = "전체"
    source = request.args.get("source", "community")
    origin = request.args.get("origin", "all")
    if origin == "public":  # 예전 주소(?origin=public)도 공공 레시피 칸으로
        source = "public"
    if source not in SOURCES:
        source = "community"
    if source == "public" or origin not in ORIGIN_FILTERS:
        origin = "all"  # 작성 방식은 커뮤니티 레시피에만 있다
    max_time = request.args.get("time", 0, type=int)
    if max_time not in TIME_FILTERS or source == "public":
        max_time = 0  # 공공 레시피에는 조리 시간 정보가 없다
    sort = "popular" if request.args.get("sort") == "popular" else "latest"

    stmt = _browse_query(source, q, category, max_time, origin)
    if sort == "popular":
        # 인기순은 좋아요 수 기준으로 계산한다 (AI 사용 안 함)
        like_count = db.select(func.count(Like.user_id)).where(Like.recipe_id == Recipe.id).correlate(Recipe).scalar_subquery()
        stmt = stmt.order_by(like_count.desc(), Recipe.created_at.desc(), Recipe.id.desc())
    elif source == "public":
        stmt = stmt.order_by(Recipe.id)  # 공공 레시피는 한꺼번에 들어와 등록 시각이 같으므로 원본 순서대로
    else:
        stmt = stmt.order_by(Recipe.created_at.desc(), Recipe.id.desc())

    page_no = max(1, request.args.get("page", 1, type=int) or 1)
    page = db.paginate(stmt, page=page_no, per_page=PER_PAGE, error_out=False)
    if page.pages and page_no > page.pages:  # 없는 페이지 번호를 넣으면 마지막 페이지로
        page = db.paginate(stmt, page=page.pages, per_page=PER_PAGE, error_out=False)
    # 칸 이름 옆에 보여 줄 개수 (검색어·요리 종류는 두 칸에 똑같이 적용)
    totals = {"community": _count(_browse_query("community", q, category, 0, "all")),
              "public": _count(_browse_query("public", q, category, 0, "all"))}
    filters = {"q": q, "category": category, "time": max_time, "origin": origin, "sort": sort, "source": source}
    return render_template("index.html", page=page, recipes=page.items, filters=filters, sources=SOURCES, totals=totals,
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
