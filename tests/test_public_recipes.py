"""공공 레시피(식품의약품안전처 조리식품의 레시피 DB) 가져오기 테스트.

실제 API 는 부르지 않고, API 응답과 같은 형식의 예시 파일(tests/data/cookrcp01_sample.json)을 쓴다.
"""
import json
import os

import pytest

from app import public_recipes as pr
from app.extensions import db
from app.models import Ingredient, Recipe, User

from conftest import MIX_ANSWER, login

SAMPLE = os.path.join(os.path.dirname(__file__), "data", "cookrcp01_sample.json")


@pytest.fixture
def rows():
    with open(SAMPLE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def imported(app, rows):
    with app.app_context():
        return pr.import_rows(rows)


def _ings(data):
    return [(i["name"], i["quantity"], i["unit"]) for i in data["ingredients"]]


# ---------- 재료 글 나누기 ----------
@pytest.mark.parametrize("token, expected", [
    ("부추 50g", ("부추", 50, "g")),
    ("달걀 30g(1/2개)", ("달걀", 0.5, "개")),          # 괄호 안이 집에서 재기 쉬운 단위면 그쪽
    ("양파 10g(3×1cm)", ("양파", 10, "g")),            # 아니면 괄호는 버린다
    ("조랭이떡(70g)", ("조랭이떡", 70, "g")),           # 양이 괄호 안에만 있는 경우
    ("소금 약간", ("소금", None, "약간")),
    ("●참기름", ("참기름", None, "")),
    ("날콩가루 7g(1⅓작은술)", ("날콩가루", 4 / 3, "작은술")),   # 원본의 특수 분수 글자
    ("물 300ml(1½컵)", ("물", 1.5, "컵")),
    ("황태(채) 15g(10개)", ("황태", 10, "개")),                 # 괄호가 두 개
    ("오이 70g(1/3개)", ("오이", 70, "g")),                     # 0.33개보다 g 이 읽기 쉽다
])
def test_parse_ingredient(token, expected):
    name, qty, unit = pr.parse_ingredient(token)
    assert (name, qty, unit) == expected


def test_parse_parts_skips_headers_and_reads_servings():
    items, servings = pr.parse_parts("[2인분]\n●주재료 : 두부 100g, 부추 10g(5줄기)\n고명\n깨 약간", "두부 부추 무침")
    assert [(i["name"], i["quantity"], i["unit"]) for i in items] == [("두부", 100, "g"), ("부추", 5, "줄기"), ("깨", None, "약간")]
    assert servings == 2


def test_parse_parts_rounds_and_dedupes():
    items, _ = pr.parse_parts("간장 3g(2/3작은술), 간장 5g", "")
    assert items == [{"name": "간장", "quantity": 0.5, "unit": "작은술"}]  # 2/3작은술 → 0.5 단위, 같은 재료는 한 번


def test_clean_step_removes_number_and_photo_letter():
    assert pr.clean_step("1. 새우를 데쳐 건진다.a") == "새우를 데쳐 건진다."
    assert pr.clean_step("  ") == ""


def test_convert_row(rows):
    data = pr.convert_row(rows[0])
    assert data["title"] == "새우 두부 계란찜"
    assert data["category"] == "반찬"
    assert data["external_id"] == "COOKRCP01:28"
    assert data["cook_time_min"] == 0              # API 에 조리 시간이 없음
    assert ("시금치", 3, "줄기") in _ings(data)    # '고명' 소제목 아래 재료도 들어간다
    assert all("새우두부계란찜" != n for n, _, _ in _ings(data))  # 첫 줄의 요리 이름은 재료가 아님
    assert data["steps"][0] == "손질된 새우를 끓는 물에 데쳐 건진다."
    assert data["info"]["nutrition"]["열량"] == (220.0, "kcal")


def test_convert_row_category_and_empty(rows):
    by_name = {r["RCP_NM"]: r for r in rows}
    assert pr.convert_row(by_name["닭가슴살 샐러드 파스타"])["category"] == "샐러드"
    assert pr.convert_row(by_name["조랭이떡 크림 수프"])["category"] == "간식·디저트"
    assert pr.convert_row(by_name["재료가 없는 레시피"]) is None


# ---------- 저장 ----------
def test_import_saves_public_recipes_once(app, rows, imported):
    assert imported == (5, 0, 1)  # 5개 저장, 재료 없는 1개 제외
    with app.app_context():
        again = pr.import_rows(rows)
        assert again == (0, 5, 1)  # 다시 실행해도 중복 저장 안 함
        assert pr.public_count() == 5
        author = db.session.scalar(db.select(User).filter_by(username=pr.PUBLIC_USERNAME))
        assert author.nickname == "식품의약품안전처"
        r = db.session.scalar(db.select(Recipe).filter_by(external_id="COOKRCP01:40"))
        assert r.origin == "public" and r.is_public and r.servings == 2 and not r.is_ai
        assert r.public_info["source"].startswith("식품의약품안전처")


def test_public_author_cannot_log_in(client, imported):
    login(client, pr.PUBLIC_USERNAME, "password123")  # 비밀번호가 임의 값이라 로그인되지 않는다
    assert client.get("/me").status_code == 302


def test_fetch_page_reports_api_errors(monkeypatch):
    class Res:
        def __init__(self, body):
            self.body = json.dumps(body).encode()

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pr.urllib.request, "urlopen",
                        lambda url, timeout: Res({"RESULT": {"CODE": "INFO-100", "MSG": "인증키가 유효하지 않습니다."}}))
    with pytest.raises(pr.PublicAPIError, match="INFO-100"):
        pr.fetch_page("bad", 1, 5)
    monkeypatch.setattr(pr.urllib.request, "urlopen",
                        lambda url, timeout: Res({"COOKRCP01": {"total_count": "2", "row": [{"RCP_SEQ": "1"}, {"RCP_SEQ": "2"}],
                                                                "RESULT": {"CODE": "INFO-000"}}}))
    assert pr.fetch_rows("key") == [{"RCP_SEQ": "1"}, {"RCP_SEQ": "2"}]


# ---------- 화면 ----------
def test_browse_separates_community_and_public(client, make_user, make_recipe, imported):
    uid = make_user()
    make_recipe(uid, title="내가 쓴 볶음밥")
    community = client.get("/").get_data(as_text=True)
    # 기본 화면은 커뮤니티 레시피만: 공공 레시피 1,000여 개가 회원 레시피를 덮지 않게
    assert "내가 쓴 볶음밥" in community and "새우 두부 계란찜" not in community
    assert "1개" in community and "5개" in community  # 두 칸의 개수
    public = client.get("/?source=public").get_data(as_text=True)
    assert "새우 두부 계란찜" in public and "내가 쓴 볶음밥" not in public
    assert "time-filter" not in public  # 공공 레시피에는 시간 정보가 없어 시간 조건을 숨긴다
    assert "새우 두부 계란찜" in client.get("/?origin=public").get_data(as_text=True)  # 예전 주소도 공공 칸으로
    assert "새우 두부 계란찜" not in client.get("/?origin=ai").get_data(as_text=True)


def test_search_hints_other_source(client, make_user, make_recipe, imported):
    uid = make_user()
    make_recipe(uid, title="두부 김치", ingredients=(("두부", 1, "모"), ("김치", 100, "g")))
    html = client.get("/?q=두부").get_data(as_text=True)
    assert "두부 김치" in html and "공공 레시피에서 보기" in html  # 공공 레시피에도 두부 요리가 있다고 알려 준다
    assert "새우 두부 계란찜" in client.get("/?q=두부&source=public").get_data(as_text=True)


def test_real_api_sample_converts_cleanly():
    """식품안전나라에서 실제로 받은 30개: 모두 변환되고, 재료량이 0.33 처럼 읽기 어려운 값이 없다."""
    with open(os.path.join(os.path.dirname(__file__), "data", "cookrcp01_real30.json"), encoding="utf-8") as f:
        real = json.load(f)
    for row in real:
        data = pr.convert_row(row)
        assert data and data["ingredients"] and data["steps"], row["RCP_NM"]
        for i in data["ingredients"]:
            assert i["name"] and len(i["name"]) <= 40
            if i["quantity"] is not None and i["unit"] not in ("g", "ml"):
                assert (i["quantity"] * 2).is_integer() or i["quantity"] >= 1, (row["RCP_NM"], i)


def test_time_filter_excludes_unknown_time(client, imported):
    assert "새우 두부 계란찜" not in client.get("/?time=30").get_data(as_text=True)
    assert "새우 두부 계란찜" in client.get("/?time=30&source=public").get_data(as_text=True)  # 공공 칸에서는 시간 조건을 무시


def test_detail_shows_source_and_nutrition(app, client, imported):
    with app.app_context():
        rid = db.session.scalar(db.select(Recipe.id).filter_by(external_id="COOKRCP01:28"))
    html = client.get(f"/recipes/{rid}").get_data(as_text=True)
    assert "식품의약품안전처" in html and "열량" in html and "220" in html
    assert "<b>0</b>분" not in html  # 시간 정보가 없으면 '0분'으로 보이지 않는다
    assert "/edit" not in html  # 다른 사람(식약처) 레시피라 수정 버튼 없음


def test_search_by_ingredient_finds_public(client, imported):
    assert "부추 콩가루 찜" in client.get("/?q=콩가루&source=public").get_data(as_text=True)


def test_pantry_candidates_include_public_and_prep_words(client, imported):
    # '다진 마늘' 은 보유 재료 '마늘' 과 같은 재료로 본다
    html = client.get("/pantry?have=부추&have=마늘&have=고춧가루").get_data(as_text=True)
    assert "부추 콩가루 찜" in html and "방울토마토 소박이" in html


def test_mix_can_use_public_recipe(app, client, make_user, make_recipe, imported, fake_ai):
    uid = make_user()
    make_recipe(uid)
    login(client)
    with app.app_context():
        rid = db.session.scalar(db.select(Recipe.id).filter_by(external_id="COOKRCP01:31"))
    html = client.get(f"/mix?other={rid}").get_data(as_text=True)
    assert "부추 콩가루 찜" in html and "시간 정보 없음" in html
    fake = fake_ai(MIX_ANSWER)
    client.post("/mix", data={"own": _own_id(app, uid), "other": rid, "goal": "", "servings": 2})
    assert "정보 없음" in fake.prompts[-1]  # 조리 시간이 없는 레시피는 AI 에도 '정보 없음'으로 전달


def _own_id(app, uid):
    with app.app_context():
        return db.session.scalar(db.select(Recipe.id).filter_by(author_id=uid))


def test_ingredient_rows_saved(app, imported):
    with app.app_context():
        n = db.session.scalar(db.select(db.func.count(Ingredient.id)).join(Recipe).where(Recipe.origin == "public"))
        assert n > 20
