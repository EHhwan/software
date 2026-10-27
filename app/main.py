"""메인 페이지 · 마이페이지"""
from flask import Blueprint, render_template
from flask_login import current_user, login_required

from .extensions import db
from .models import Recipe

bp = Blueprint("main", __name__)

HOME_LIMIT = 6  # 메인 페이지에 보여 줄 레시피 수


@bp.route("/")
def index():
    latest = db.session.scalars(
        db.select(Recipe).filter_by(is_public=True).order_by(Recipe.created_at.desc()).limit(HOME_LIMIT)
    ).all()
    # TODO(3차): 좋아요 수 기준 인기 레시피 (AI 사용 안 함)
    return render_template("index.html", latest=latest)


@bp.route("/me")
@login_required
def mypage():
    mine = [r for r in current_user.recipes if not r.is_ai]
    ai_made = [r for r in current_user.recipes if r.is_ai]
    return render_template("mypage.html", mine=mine, ai_made=ai_made)
