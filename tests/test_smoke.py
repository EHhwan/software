"""기본 틀이 뜨는지 확인하는 테스트. 실행: python -m pytest tests -q"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import ai  # noqa: E402
import app as service  # noqa: E402


@pytest.fixture
def client():
    service.app.config["TESTING"] = True
    with service.app.test_client() as c:
        yield c


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200 and service.SERVICE_NAME in r.get_data(as_text=True)


def test_404(client):
    assert client.get("/no-such-page").status_code == 404


def test_ai_without_key_raises(monkeypatch):
    monkeypatch.setattr(ai, "_model", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ai.AIUnavailable):
        ai.ask("안녕")
