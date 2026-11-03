"""2·3차: 레시피 등록·수정·삭제, 둘러보기(검색·필터·정렬), 좋아요·즐겨찾기, 재료량 표시"""
import sqlite3

import pytest
from conftest import login

from app import create_app
from app.extensions import db
from app.models import Ingredient, Like, Recipe
from app.recipe_util import format_quantity, parse_quantity


def recipe_form(**over):
    data = {"title": "토마토 달걀볶음", "category": "반찬", "description": "가벼운 반찬", "servings": "2", "cook_time_min": "15",
            "ing_name": ["토마토", "달걀", "소금", ""], "ing_qty": ["2", "1/2", "약간", ""], "ing_unit": ["개", "판", "", ""],
            "step": ["토마토를 썬다", "", "달걀과 볶는다"], "visibility": "public"}
    data.update(over)
    return data


# ---------- 재료량 ----------
@pytest.mark.parametrize("q,unit,factor,expected", [
    (3, "개", 1.5, "4~5"), (3, "개", 0.5, "1~2"), (2, "개", 1.5, "3"), (0.5, "대", 1, "1/2"), (0.5, "대", 1.5, "1"),
    (1, "큰술", 0.5, "1/2"), (1, "큰술", 1.5, "1.5"), (200, "g", 1 / 3, "67"), (0.3, "개", 0.5, "1"), (None, "약간", 2, ""),
])
def test_format_quantity(q, unit, factor, expected):
    assert format_quantity(q, unit, factor) == expected


@pytest.mark.parametrize("text,expected", [("2", 2), ("0.5", 0.5), ("1/2", 0.5), ("1 1/2", 1.5), ("", None)])
def test_parse_quantity(text, expected):
    assert parse_quantity(text) == expected


@pytest.mark.parametrize("text", ["약간", "-1", "1/0", "nan"])
def test_parse_quantity_rejects(text):
    with pytest.raises(ValueError):
        parse_quantity(text)


# ---------- 등록 · 수정 · 삭제 ----------
def test_create_requires_login(client):
    r = client.get("/recipes/new")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_create_recipe(client, app, make_user):
    make_user()
    login(client)
    r = client.post("/recipes/new", data=recipe_form())
    assert r.status_code == 302
    with app.app_context():
        rec = db.session.scalar(db.select(Recipe))
        assert [(i.name, i.quantity, i.unit) for i in rec.ingredients] == [("토마토", 2, "개"), ("달걀", 0.5, "판"), ("소금", None, "약간")]
        assert [s.content for s in rec.steps] == ["토마토를 썬다", "달걀과 볶는다"]  # 빈 단계는 무시
        assert rec.category == "반찬" and rec.is_public and rec.origin == "user"
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "토마토 달걀볶음" in page and "1/2판" in page and "약간" in page


@pytest.mark.parametrize("over,message", [
    ({"title": ""}, "요리 이름"), ({"category": "없는 종류"}, "요리 종류"), ({"servings": "0"}, "인분"),
    ({"cook_time_min": "abc"}, "조리 시간"), ({"ing_name": [""], "ing_qty": [""], "ing_unit": [""]}, "재료를 한 개 이상"),
    ({"step": ["", " "]}, "조리 순서를 한 단계"), ({"ing_name": ["소금"], "ing_qty": ["많이"], "ing_unit": ["g"]}, "숫자"),
])
def test_create_validation(client, app, make_user, over, message):
    make_user()
    login(client)
    r = client.post("/recipes/new", data=recipe_form(**over))
    assert r.status_code == 400 and message in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Recipe.id))) == 0


def test_only_author_can_edit_or_delete(client, app, make_user, make_recipe):
    owner, other = make_user(), make_user("other01", "남")
    rid = make_recipe(owner)
    login(client, "other01")
    assert client.get(f"/recipes/{rid}/edit").status_code == 403
    assert client.post(f"/recipes/{rid}/edit", data=recipe_form()).status_code == 403
    assert client.post(f"/recipes/{rid}/delete").status_code == 403
    client.post("/logout")
    login(client)
    assert client.post(f"/recipes/{rid}/edit", data=recipe_form(title="고친 이름")).status_code == 302
    with app.app_context():
        assert db.session.get(Recipe, rid).title == "고친 이름"
    assert client.post(f"/recipes/{rid}/delete").status_code == 302
    with app.app_context():
        assert db.session.get(Recipe, rid) is None
        assert db.session.scalar(db.select(db.func.count(Ingredient.id))) == 0


def test_private_recipe_hidden_from_others(client, make_user, make_recipe):
    owner = make_user()
    make_user("other01", "남")
    rid = make_recipe(owner, title="비밀 레시피", public=False)
    assert client.get(f"/recipes/{rid}").status_code == 404
    assert "비밀 레시피" not in client.get("/").get_data(as_text=True)
    login(client, "other01")
    assert client.get(f"/recipes/{rid}").status_code == 404
    client.post("/logout")
    login(client)
    assert client.get(f"/recipes/{rid}").status_code == 200
    client.post(f"/recipes/{rid}/visibility")
    client.post("/logout")
    assert client.get(f"/recipes/{rid}").status_code == 200  # 공개로 바꾸면 누구나 볼 수 있다


# ---------- 둘러보기 ----------
def test_browse_search_filter_sort(client, app, make_user, make_recipe):
    a, b = make_user(), make_user("other01", "남")
    r1 = make_recipe(a, "김치볶음밥", minutes=20)
    r2 = make_recipe(a, "들기름 국수", category="면", minutes=10, ingredients=(("국수", 200, "g"), ("들기름", 2, "큰술")))
    r3 = make_recipe(b, "100% 버섯전", category="반찬", minutes=40, origin="ai_mix", ingredients=(("버섯", 100, "g"),))
    with app.app_context():
        db.session.add_all([Like(user_id=a, recipe_id=r3), Like(user_id=b, recipe_id=r3), Like(user_id=b, recipe_id=r2)])
        db.session.commit()

    def titles(url):
        page = client.get(url).get_data(as_text=True)
        return [t for t in ("김치볶음밥", "들기름 국수", "100% 버섯전") if f">{t}</a>" in page]

    assert titles("/?q=들기름") == ["들기름 국수"]          # 재료 이름으로 검색
    assert titles("/?q=김치") == ["김치볶음밥"]
    assert titles("/?q=%25") == ["100% 버섯전"]            # % 는 그대로 검색 (와일드카드 아님)
    assert titles("/?category=면") == ["들기름 국수"]
    assert titles("/?time=15") == ["들기름 국수"]
    assert titles("/?origin=ai") == ["100% 버섯전"]
    assert titles("/?origin=user") == ["김치볶음밥", "들기름 국수"]
    page = client.get("/?sort=popular").get_data(as_text=True)
    assert page.index(">100% 버섯전</a>") < page.index(">들기름 국수</a>") < page.index(">김치볶음밥</a>")  # 좋아요 2 > 1 > 0
    assert "조건에 맞는 레시피가 없어요" in client.get("/?q=없는요리").get_data(as_text=True)


# ---------- 좋아요 · 즐겨찾기 ----------
def test_like_toggle_once_per_user(client, app, make_user, make_recipe):
    rid = make_recipe(make_user())
    assert client.post(f"/recipes/{rid}/like").status_code == 302  # 로그인 필요
    login(client)
    r = client.post(f"/recipes/{rid}/like", headers={"Accept": "application/json"})
    assert r.get_json() == {"on": True, "count": 1, "message": "좋아요를 눌렀어요."}
    r = client.post(f"/recipes/{rid}/like", headers={"Accept": "application/json"})
    assert r.get_json()["on"] is False and r.get_json()["count"] == 0


def test_bookmark_shows_in_favorites(client, make_user, make_recipe):
    me = make_user()
    rid = make_recipe(make_user("other01", "남"), "버섯 리소토")
    login(client)
    assert "버섯 리소토" not in client.get("/me?tab=favorites").get_data(as_text=True)
    client.post(f"/recipes/{rid}/bookmark", data={"next": "/"})
    assert "버섯 리소토" in client.get("/me?tab=favorites").get_data(as_text=True)
    assert me


def test_cannot_like_private_recipe_of_others(client, make_user, make_recipe):
    rid = make_recipe(make_user(), public=False)
    make_user("other01", "남")
    login(client, "other01")
    assert client.post(f"/recipes/{rid}/like").status_code == 404


# ---------- 1차 DB 자동 업그레이드 ----------
def test_old_database_gets_category_column(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(20), nickname VARCHAR(12), password_hash VARCHAR(255), created_at DATETIME)")
    con.execute("CREATE TABLE recipes (id INTEGER PRIMARY KEY, author_id INTEGER, title VARCHAR(60), description TEXT, servings INTEGER, "
                "cook_time_min INTEGER, origin VARCHAR(20), ai_note TEXT, is_public BOOLEAN, created_at DATETIME, updated_at DATETIME)")
    con.commit()
    con.close()
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}"})
    with app.app_context():
        cols = {c["name"] for c in db.inspect(db.engine).get_columns("recipes")}
        assert "category" in cols
        db.engine.dispose()
