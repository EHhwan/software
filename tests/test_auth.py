"""1차 테스트: 기본 구조, DB, 회원 기능. 실행: python -m pytest tests -q"""
import os
import sys

import pytest
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ai, create_app  # noqa: E402
from app.config import database_url  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Ingredient, Like, Recipe, RecipeSource, Step, User  # noqa: E402


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,  # CSRF 는 아래 test_csrf_is_enforced 에서 따로 확인
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
    })
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username="cook01", nickname="요리왕", password="password123", password2=None):
    return client.post("/register", data={
        "username": username, "nickname": nickname,
        "password": password, "password2": password if password2 is None else password2,
    })


def login(client, username="cook01", password="password123", next_url=None):
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={"username": username, "password": password})


# ---------- 기본 구조 ----------
def test_index_and_404(client):
    assert client.get("/").status_code == 200
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "없는 페이지" in r.get_data(as_text=True)


def test_database_url(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url(str(tmp_path)).startswith("sqlite:///")
    for given in ("postgres://u:p@host:5432/db", "postgresql://u:p@host:5432/db"):  # Render 형식 변환
        monkeypatch.setenv("DATABASE_URL", given)
        assert database_url(str(tmp_path)) == "postgresql+psycopg2://u:p@host:5432/db"


# ---------- 회원가입 ----------
def test_register_logs_in_and_hashes_password(client, app):
    r = register(client, username="  Cook01 ")
    assert r.status_code == 302 and r.headers["Location"].endswith("/me")
    with app.app_context():
        u = db.session.scalar(db.select(User).filter_by(username="cook01"))  # 소문자·공백 제거로 저장
        assert u.password_hash != "password123" and u.check_password("password123")
    assert "요리왕" in client.get("/me").get_data(as_text=True)


@pytest.mark.parametrize("kwargs,message", [
    ({"username": "ab"}, "4~20자"),
    ({"username": "한글아이디"}, "4~20자"),
    ({"nickname": "a"}, "2~12자"),
    ({"password": "short"}, "8~64자"),
    ({"password2": "different123"}, "서로 달라요"),
])
def test_register_validation(client, app, kwargs, message):
    r = register(client, **kwargs)
    assert r.status_code == 400 and message in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0


def test_register_duplicate_username_and_nickname(client):
    register(client)
    client.post("/logout")
    r = register(client, username="COOK01", nickname="다른이름")
    assert r.status_code == 400 and "이미 사용 중인 아이디" in r.get_data(as_text=True)
    r = register(client, username="cook02", nickname="요리왕")
    assert r.status_code == 400 and "이미 사용 중인 닉네임" in r.get_data(as_text=True)


# ---------- 로그인 · 로그아웃 ----------
def test_login_success_and_failure(client):
    register(client)
    client.post("/logout")
    r = login(client, password="wrong-password")
    assert r.status_code == 401 and "아이디 또는 비밀번호가 맞지 않아요" in r.get_data(as_text=True)
    r = login(client, username="nobody")
    assert r.status_code == 401 and "아이디 또는 비밀번호가 맞지 않아요" in r.get_data(as_text=True)  # 같은 문구
    assert login(client, username="COOK01").status_code == 302


def test_mypage_requires_login_and_returns_after_login(client):
    register(client)
    client.post("/logout")
    r = client.get("/me")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    r = login(client, next_url="/me")
    assert r.headers["Location"].endswith("/me")


@pytest.mark.parametrize("bad", ["//evil.example", "https://evil.example/", "/\\evil.example", "evil"])
def test_login_blocks_open_redirect(client, bad):
    register(client)
    client.post("/logout")
    r = login(client, next_url=bad)
    assert r.status_code == 302 and r.headers["Location"] == "/"


def test_logout_is_post_only(client):
    register(client)
    assert client.get("/logout").status_code == 405
    client.post("/logout")
    assert client.get("/me").status_code == 302


def test_csrf_is_enforced(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'csrf.db'}"})
    r = register(app.test_client())  # 토큰 없이 보낸 요청
    assert r.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0
        db.engine.dispose()


# ---------- DB 구조 (2차 이후에 쓰는 테이블) ----------
def _make_recipe(user, title="김치볶음밥", origin="user"):
    r = Recipe(author=user, title=title, description="", servings=2, cook_time_min=20, origin=origin)
    r.ingredients = [Ingredient(position=1, name="김치", quantity=200, unit="g"),
                     Ingredient(position=2, name="소금", quantity=None, unit="약간")]
    r.steps = [Step(number=1, content="김치를 볶는다"), Step(number=2, content="밥을 넣는다")]
    return r


def test_like_once_per_user_per_recipe(app):
    with app.app_context():
        u = User(username="a1234", nickname="에이")
        u.set_password("password123")
        r = _make_recipe(u)
        db.session.add_all([u, r])
        db.session.commit()
        db.session.add(Like(user_id=u.id, recipe_id=r.id))
        db.session.commit()
        db.session.add(Like(user_id=u.id, recipe_id=r.id))
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_recipe_delete_cascades_and_source_is_kept(app):
    with app.app_context():
        u = User(username="a1234", nickname="에이")
        u.set_password("password123")
        mine, other = _make_recipe(u), _make_recipe(u, title="된장찌개")
        db.session.add_all([u, mine, other])
        db.session.commit()
        mixed = _make_recipe(u, title="김치된장볶음밥", origin="ai_mix")
        db.session.add(mixed)
        mixed.sources = [RecipeSource(position=1, source_recipe_id=mine.id, source_title=mine.title, source_author="에이"),
                         RecipeSource(position=2, source_recipe_id=other.id, source_title=other.title, source_author="에이")]
        db.session.add(mixed)
        db.session.commit()
        mixed_id, other_id = mixed.id, other.id

        db.session.delete(other)  # 원본 레시피 하나를 삭제해도
        db.session.commit()
        db.session.expire_all()
        assert db.session.scalar(db.select(db.func.count(Ingredient.id)).filter_by(recipe_id=other_id)) == 0
        src = db.session.get(Recipe, mixed_id).sources[1]
        assert src.source_recipe_id is None and src.source_title == "된장찌개"  # 출처 제목은 남는다


def test_ai_without_key_raises(monkeypatch):
    monkeypatch.setattr(ai, "_model", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ai.AIUnavailable):
        ai.ask("안녕")
