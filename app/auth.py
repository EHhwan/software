"""회원가입 · 로그인 · 로그아웃"""
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .forms import LoginForm, RegisterForm
from .models import User

bp = Blueprint("auth", __name__)


def _safe_next(target):
    """로그인 후 돌아갈 주소. 우리 사이트 안의 경로(/...)만 허용한다 (다른 사이트로 보내는 피싱 방지)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    parts = urlsplit(target)
    return None if parts.scheme or parts.netloc else target


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.mypage"))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, nickname=form.nickname.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:  # 검사와 저장 사이에 다른 사람이 같은 아이디로 먼저 가입한 경우
            db.session.rollback()
            flash("방금 다른 사람이 같은 아이디나 닉네임으로 가입했어요. 다른 값으로 다시 시도해 주세요.", "danger")
            return render_template("auth/register.html", form=form), 409
        login_user(user)
        flash(f"{user.nickname}님, 가입을 환영해요! 🍳", "success")
        return redirect(url_for("main.mypage"))
    return render_template("auth/register.html", form=form), 400 if form.errors else 200


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.mypage"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).filter_by(username=form.username.data))
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash(f"{user.nickname}님, 반가워요!", "success")
            return redirect(_safe_next(request.args.get("next")) or url_for("main.index"))
        # 아이디가 없는지 비밀번호가 틀렸는지 구분하지 않는다 (가입된 아이디를 알아내지 못하게)
        flash("아이디 또는 비밀번호가 맞지 않아요.", "danger")
        return render_template("auth/login.html", form=form), 401
    return render_template("auth/login.html", form=form), 400 if form.errors else 200


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("로그아웃했어요.", "info")
    return redirect(url_for("main.index"))
