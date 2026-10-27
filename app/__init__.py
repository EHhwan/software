"""레시피 믹스 - Flask 앱을 만드는 곳 (application factory)."""
import os
import sqlite3
from datetime import timedelta

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError
from sqlalchemy import event
from sqlalchemy.engine import Engine

try:  # .env 파일의 GEMINI_API_KEY, SECRET_KEY 등을 환경변수로 읽는다 (배포 서버에서는 환경변수를 직접 등록)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .config import Config, database_url
from .extensions import csrf, db, login_manager

SERVICE_NAME = "레시피 믹스"


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(dbapi_conn, _record):
    """SQLite 는 기본으로 외래키 제약(ON DELETE CASCADE 등)을 검사하지 않으므로 연결할 때마다 켠다."""
    if isinstance(dbapi_conn, sqlite3.Connection):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def create_app(overrides=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url(app.instance_path)
    if overrides:
        app.config.update(overrides)
    if app.config["SECRET_KEY"] == "dev-change-me" and not (app.debug or app.testing):
        app.logger.warning("SECRET_KEY 가 기본값이에요. 배포할 때는 환경변수로 꼭 바꿔 주세요.")

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "로그인이 필요한 기능이에요."
    login_manager.login_message_category = "warning"

    from . import models  # noqa: F401  (create_all 이 테이블을 알 수 있게 모델을 불러온다)
    from .auth import bp as auth_bp
    from .main import bp as main_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    @app.context_processor
    def inject_globals():
        return {"SERVICE_NAME": SERVICE_NAME}

    @app.template_filter("kst")
    def kst(value, fmt="%Y.%m.%d"):
        """DB 의 UTC 시각 → 한국 시간 문자열"""
        return (value + timedelta(hours=9)).strftime(fmt) if value else ""

    @app.errorhandler(CSRFError)
    def csrf_error(_e):
        flash("요청이 만료됐어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.", "danger")
        return redirect(request.referrer or url_for("main.index"))

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()  # 없는 테이블만 만든다 (이미 있는 테이블·데이터는 그대로)

    return app
