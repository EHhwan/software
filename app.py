"""공지핏 - 나에게 해당되는 학교 공지만 골라 요약해 주는 AI 비서 (3회차 기본 틀)

지금은 화면 뼈대와 환경 설정만 들어 있다. 기능은 일정(9~12주차)에 맞춰 채워 나간다.
"""
import os
import sqlite3
import time

from flask import Flask, g, render_template

try:  # .env 파일의 GEMINI_API_KEY 등을 환경변수로 읽는다 (배포 서버에서는 환경변수를 직접 등록)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 마감일 판단은 서버 시각 기준이다. 배포 서버(Render 등)는 보통 UTC 라서 한국 시간으로 고정한다.
# (Windows 에는 tzset 이 없어 로컬 PC 시간 그대로 사용)
os.environ.setdefault("TZ", "Asia/Seoul")
if hasattr(time, "tzset"):
    time.tzset()

SERVICE_NAME = "공지핏"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

DATABASE = os.environ.get("APP_DB", os.path.join(app.root_path, "app.db"))

# TODO(9주차): 데이터 모델 설계 후 테이블 정의 (예: 사용자 프로필, 공지, AI 분석 결과)
SCHEMA = """
"""


# ---------- DB ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=15)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript(SCHEMA)
    db.commit()
    db.close()


@app.context_processor
def inject_globals():
    return {"SERVICE_NAME": SERVICE_NAME}


# ---------- 라우트 ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


init_db()

if __name__ == "__main__":
    app.run(debug=True)
