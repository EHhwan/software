"""환경변수로 바뀌는 설정. 비밀 값(API 키, SECRET_KEY, DB 주소)은 코드에 적지 않고 .env 나 배포 플랫폼에 둔다."""
import os
from datetime import timedelta


def database_url(instance_path):
    """DATABASE_URL 이 있으면 그 DB(배포용 PostgreSQL), 없으면 instance 폴더의 SQLite(개발용)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + os.path.join(instance_path, "recipe_mix.db")
    # Render 등은 postgres:// 로 주는데 SQLAlchemy 는 postgres:// 를 인식하지 못하고,
    # SQLAlchemy 2.1 부터는 드라이버를 안 적으면 psycopg(3) 를 찾으므로 설치한 psycopg2 를 직접 지정한다
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}  # 오래 쉰 DB 연결이 끊겨 있어도 다시 연결

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=14)  # '로그인 유지' 를 체크했을 때
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    WTF_CSRF_TIME_LIMIT = None  # 폼을 오래 띄워 둬도(레시피 작성 중) 토큰이 만료되지 않게
