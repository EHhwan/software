"""테스트 공용 준비물: 앱, 클라이언트, 사용자·레시피 만들기, 가짜 Gemini"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)

from app import ai, create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Recipe, User  # noqa: E402
from app.services import apply_recipe_data  # noqa: E402


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}"})
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    def make(username="cook01", nickname="요리왕", password="password123"):
        with app.app_context():
            u = User(username=username, nickname=nickname)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            return u.id
    return make


@pytest.fixture
def make_recipe(app):
    def make(author_id, title="김치볶음밥", public=True, category="밥·덮밥·볶음밥", minutes=20, servings=2,
             ingredients=(("밥", 2, "공기"), ("김치", 200, "g"), ("대파", 0.5, "대")), origin="user"):
        with app.app_context():
            r = Recipe(author_id=author_id, origin=origin)
            apply_recipe_data(r, {"title": title, "description": "설명", "category": category, "servings": servings,
                                  "cook_time_min": minutes, "is_public": public, "steps": ["볶는다", "섞는다"],
                                  "ingredients": [{"name": n, "quantity": q, "unit": u} for n, q, u in ingredients]})
            db.session.add(r)
            db.session.commit()
            return r.id
    return make


def login(client, username="cook01", password="password123"):
    return client.post("/login", data={"username": username, "password": password})


class FakeModel:
    """Gemini 대신 정해 둔 답을 돌려준다. exc 를 주면 그 오류를 낸다."""
    def __init__(self, answer=None, exc=None):
        self.answer, self.exc, self.prompts = answer, exc, []

    def generate_content(self, prompt, **_kw):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer, ensure_ascii=False)
        return type("R", (), {"text": text})()


@pytest.fixture
def fake_ai(monkeypatch):
    def use(answer=None, exc=None):
        m = FakeModel(answer, exc)
        monkeypatch.setattr(ai, "_model", m)
        return m
    return use


MIX_ANSWER = {
    "title": "버섯 크림 김치볶음밥", "summary": "김치의 산미에 크림의 부드러움", "cook_time_min": 25, "servings": 99,
    "ingredients": [{"name": "밥", "quantity": 2, "unit": "공기"}, {"name": "김치", "quantity": "200", "unit": "g"},
                    {"name": "소금", "quantity": None, "unit": "약간"}, {"name": "", "quantity": 1, "unit": "개"}],
    "steps": ["버섯을 먼저 볶는다", "  ", "김치와 밥을 넣는다"],
    "changes": [{"type": "add", "item": "김치", "basis": "B", "before": "없음", "after": "김치 200g", "reason": "특징 살리기"},
                {"type": "explode", "item": "이상한 값", "basis": "A"},
                {"type": "quantity", "item": "우유", "basis": "b", "before": "200ml", "after": "100ml", "reason": "질어짐 방지"}],
    "notes": "간을 마지막에 확인",
}

ADAPT_ANSWER = {
    "title": "쪽파 달걀 덮밥", "summary": "대파 대신 쪽파", "cook_time_min": 15,
    "ingredients": [{"name": "밥", "quantity": 2, "unit": "공기"}, {"name": "달걀", "quantity": 3, "unit": "개"}],
    "steps": ["쪽파를 썬다", "달걀을 볶는다"], "reason": "가진 재료로 거의 다 만들 수 있어요",
    "substitutions": [{"missing": "대파", "substitute": "쪽파", "how": "향이 순해져요"}, {"missing": "간장", "substitute": None, "how": ""}],
    "still_needed": [{"name": "간장", "quantity": 1, "unit": "큰술"}],
}
