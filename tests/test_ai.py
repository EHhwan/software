"""'한 줄로 번개 만들기' 테스트. 실제 Gemini 대신 가짜 응답을 넣어 키 없이도 돌아간다.
실행: python -m pytest tests -q
"""
import json
import os
import sys
import tempfile
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CAMPUS_FIT_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import ai   # noqa: E402
import app as campus  # noqa: E402

CATS = campus.CATEGORIES
DURS = campus.DURATIONS
NOW = datetime(2026, 10, 27, 14, 20)  # 화요일


def good_answer(**over):
    d = {"title": "배드민턴 같이 칠 사람", "category": "스포츠", "meet_time": "2026-10-28 18:00",
         "duration_min": 90, "max_people": 4, "location": "체육관", "description": "라켓 있으면 가져오기"}
    d.update(over)
    return d


# ---------- validate(): AI 답 검증 ----------
def test_valid_answer_passes():
    out = ai.validate(good_answer(), NOW, CATS, DURS)
    assert out == {"title": "배드민턴 같이 칠 사람", "category": "스포츠", "meet_time": "2026-10-28T18:00",
                   "duration": 90, "max_people": 4, "location": "체육관", "description": "라켓 있으면 가져오기"}


@pytest.mark.parametrize("cat", ["운동", "Sports", None, 3])
def test_unknown_category_is_dropped(cat):
    assert ai.validate(good_answer(category=cat), NOW, CATS, DURS)["category"] is None


@pytest.mark.parametrize("t", ["2026-10-27 14:00", "2027-01-01 10:00", "내일 6시", None, "2026-13-01 10:00"])
def test_past_far_or_broken_time_is_dropped(t):
    assert ai.validate(good_answer(meet_time=t), NOW, CATS, DURS)["meet_time"] is None


def test_same_minute_is_allowed():  # 기존 /new 와 같은 분 단위 기준
    assert ai.validate(good_answer(meet_time="2026-10-27 14:20"), NOW.replace(second=40), CATS, DURS)["meet_time"]


@pytest.mark.parametrize("given,expected", [(90, 90), (100, 90), (45, 30), (500, 240), ("60", 60), (0, None), (None, None)])
def test_duration_snaps_to_choices(given, expected):
    assert ai.validate(good_answer(duration_min=given), NOW, CATS, DURS)["duration"] == expected


@pytest.mark.parametrize("n,expected", [(2, 2), (50, 50), (1, None), (51, None), ("세 명", None), (None, None)])
def test_people_range(n, expected):
    assert ai.validate(good_answer(max_people=n), NOW, CATS, DURS)["max_people"] == expected


def test_text_lengths_are_limited():
    out = ai.validate(good_answer(title="가" * 80, location="나" * 80, description=None), NOW, CATS, DURS)
    assert len(out["title"]) == 40 and len(out["location"]) == 40 and out["description"] == ""
    assert ai.validate(good_answer(title="a"), NOW, CATS, DURS)["title"] is None


def test_non_object_answer_raises():
    with pytest.raises(ai.AIUnavailable):
        ai.validate(["not", "a", "dict"], NOW, CATS, DURS)


def test_prompt_has_reference_time_and_choices():
    p = ai.build_prompt("내일 6시 배드민턴", NOW, CATS, DURS)
    assert "2026-10-27 14:20 (화요일" in p and '"스포츠"' in p and "[30, 60, 90, 120, 180, 240]" in p
    assert p.rstrip().endswith("내일 6시 배드민턴")  # 사용자 문장은 지시문 뒤에 데이터로만 붙는다


# ---------- _ask_gemini(): 실패 처리 ----------
class FakeModel:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.prompts = text, exc, []

    def generate_content(self, prompt, **_kw):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return type("R", (), {"text": self.text})()


@pytest.fixture
def fake(monkeypatch):
    def use(**kw):
        m = FakeModel(**kw)
        monkeypatch.setattr(ai, "_model", m)
        return m
    return use


def test_broken_json_raises(fake):
    fake(text="네! 배드민턴 모임이네요")
    with pytest.raises(ai.AIUnavailable):
        ai.draft_post("내일 6시 배드민턴", NOW, CATS, DURS)


def test_network_error_raises(fake):
    fake(exc=TimeoutError("deadline exceeded"))
    with pytest.raises(ai.AIUnavailable):
        ai.draft_post("내일 6시 배드민턴", NOW, CATS, DURS)


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(ai, "_model", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ai.AIUnavailable):
        ai.draft_post("내일 6시 배드민턴", NOW, CATS, DURS)


# ---------- /api/ai/draft ----------
@pytest.fixture
def client():
    campus.app.config["TESTING"] = True
    with campus.app.test_client() as c:
        with c.session_transaction() as s:
            s["csrf"] = "tok"
        db = campus.sqlite3.connect(campus.DATABASE)
        db.execute("DELETE FROM ai_calls")
        db.commit()
        db.close()
        yield c


def post(c, text, token="tok"):
    return c.post("/api/ai/draft", data={"text": text, "csrf_token": token})


def test_api_fills_fields(client, fake):
    answer = good_answer(meet_time="2099-01-01 18:00", location=None)
    fake(text=json.dumps(answer, ensure_ascii=False))
    r = post(client, "내일 6시 체육관 배드민턴 3명")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["fields"]["category"] == "스포츠"
    assert body["missing"] == ["meet_time", "location"]  # 너무 먼 날짜는 버리고, 장소는 문장에 없음


def test_api_ai_failure_returns_503_with_message(client, fake):
    fake(exc=RuntimeError("quota exceeded"))
    r = post(client, "내일 6시 배드민턴")
    assert r.status_code == 503 and "직접 입력" in r.get_json()["error"]


@pytest.mark.parametrize("text", ["짧음", "가" * 201, "    "])
def test_api_rejects_bad_length_without_calling_ai(client, fake, text):
    m = fake(text="{}")
    assert post(client, text).status_code == 400
    assert m.prompts == []


def test_api_rate_limit(client, fake):
    m = fake(text=json.dumps(good_answer(), ensure_ascii=False))
    codes = [post(client, "내일 6시 배드민턴").status_code for _ in range(campus.AI_LIMIT + 2)]
    assert codes == [200] * campus.AI_LIMIT + [429, 429]
    assert len(m.prompts) == campus.AI_LIMIT  # 제한에 걸린 요청은 Gemini 를 부르지 않는다


def test_api_requires_csrf(client, fake):
    m = fake(text="{}")
    r = post(client, "내일 6시 배드민턴", token="wrong")
    assert r.status_code == 302 and m.prompts == []
