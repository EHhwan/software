"""공공 레시피 가져오기: 식품의약품안전처 '조리식품의 레시피 DB' (식품안전나라 OpenAPI, 서비스 COOKRCP01)

1) fetch_rows()      : API 에서 레시피 원본(JSON)을 받는다. 한 번에 최대 1000개라 나눠서 받는다.
2) convert_row()     : 원본 한 건을 우리 레시피 형식(제목·분류·재료·조리 순서)으로 바꾼다.
                       재료는 '연두부 75g(3/4모), 칵테일새우 20g(5마리)' 같은 글이라 이름·양·단위로 나눈다.
3) import_rows()     : DB 에 저장한다. 같은 레시피(일련번호)는 다시 넣지 않으므로 여러 번 실행해도 된다.
                       재료 나누는 방식을 고치면(PARSER_VERSION) 이미 있는 레시피도 다시 정리한다.

공공 레시피는 '식품의약품안전처' 사용자 이름으로 저장되고 origin="public" 으로 구분된다.
인증키(FOODSAFETY_API_KEY)는 .env 나 배포 서버 환경변수에만 넣는다.
"""
import json
import re
import secrets
import urllib.error
import urllib.request

from sqlalchemy import or_

from .extensions import db
from .models import Recipe, User
from .recipe_util import HALF_UNITS, WHOLE_UNITS, parse_quantity
from .services import apply_recipe_data

SERVICE = "COOKRCP01"
API_URL = "http://openapi.foodsafetykorea.go.kr/api/{key}/{service}/json/{start}/{end}"
PAGE_SIZE = 1000                      # API 한 번에 받을 수 있는 최대 개수
PUBLIC_USERNAME = "public_recipes"    # 공공 레시피 작성자 (로그인용 계정 아님)
PUBLIC_NICKNAME = "식품의약품안전처"
SOURCE_NAME = "식품의약품안전처 조리식품의 레시피 DB (식품안전나라)"
# 재료 나누는 방식을 고치면 1 올린다. 예전 방식으로 저장된 레시피는 서버를 켤 때 새 방식으로 다시 정리한다.
PARSER_VERSION = 2


class PublicAPIError(Exception):
    pass


# ---------- 1) 받기 ----------
def fetch_page(key, start, end, timeout=30):
    url = API_URL.format(key=key, service=SERVICE, start=start, end=end)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            body = json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise PublicAPIError(f"공공 레시피 API에 연결하지 못했어요: {e}") from e
    data = body.get(SERVICE) or {}
    result = data.get("RESULT") or body.get("RESULT") or {}
    code = result.get("CODE", "")
    if code == "INFO-200":  # 해당하는 데이터가 없음 (끝까지 받았음)
        return 0, []
    if code != "INFO-000":
        raise PublicAPIError(f"공공 레시피 API 오류 {code}: {result.get('MSG', '알 수 없는 응답')} (인증키를 확인해 주세요)")
    return int(data.get("total_count") or 0), data.get("row") or []


def fetch_rows(key, limit=None):
    """레시피 원본 전체(또는 limit 개)를 받는다."""
    total, rows = fetch_page(key, 1, min(PAGE_SIZE, limit or PAGE_SIZE))
    want = min(total, limit) if limit else total
    while len(rows) < want:
        start = len(rows) + 1
        _, more = fetch_page(key, start, min(start + PAGE_SIZE - 1, want))
        if not more:
            break
        rows += more
    return rows[:want] if want else rows


# ---------- 2) 우리 형식으로 바꾸기 ----------
NO_AMOUNT = ("약간", "적당량", "적량", "조금", "소량", "少")
HOME_UNITS = WHOLE_UNITS | HALF_UNITS
_NUMBER = r"(?:\d+\s+)?\d+(?:\.\d+)?(?:\s*/\s*\d+)?"   # 2, 0.5, 1/2, 1 1/3
_FRACTIONS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅛": "1/8"}


def _plain_fractions(text):
    """'1⅓작은술' → '1 1/3작은술', '½컵' → '1/2컵' (원본에 특수 분수 글자가 섞여 있다)"""
    for ch, frac in _FRACTIONS.items():
        text = re.sub(rf"(\d){ch}", rf"\1 {frac}", text).replace(ch, frac)
    return text


def _split_outside_parens(line):
    """쉼표로 나누되 괄호 안의 쉼표는 나누지 않는다: '두부 75g(3/4모, 부침용), 새우 20g'"""
    parts, depth, buf = [], 0, ""
    for ch in line:
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth:
            depth -= 1
        if ch in ",，" and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _amount(text):
    """'75g' → (75.0, 'g'), '1/2개' → (0.5, '개'), '약간' → (None, '약간'), 숫자 없음 → None"""
    text = text.strip()
    m = re.match(rf"^({_NUMBER})\s*([^\d()]*)$", text)
    if m:
        try:
            return parse_quantity(m.group(1)), m.group(2).strip()[:20]
        except ValueError:
            return None
    if text in NO_AMOUNT:
        return None, text
    return None


def parse_ingredient(token):
    """재료 한 개: '연두부 75g(3/4모)', '조랭이떡(70g)', '소금 약간', '참기름' → (이름, 양, 단위) 또는 None"""
    token = _plain_fractions(re.sub(r"^[●•·\-*▶◆■□○◎]+", "", token).strip())
    if not token:
        return None
    # '이름(70g)' : 양이 괄호 안에 있는 경우
    m = re.match(r"^(.+?)\s*\(([^()]*)\)\s*$", token)
    if m and not re.search(r"\d", m.group(1)) and re.search(r"\d", m.group(2)):
        amt = _amount(m.group(2).split(",")[0])
        if amt:
            return _clean_name(m.group(1)), amt[0], amt[1]
    # '이름 30g(1/2개)' : 괄호 안이 집에서 재기 쉬운 단위(개·큰술·줄기…)면 그쪽을 쓰고, 아니면 괄호는 버린다
    base = re.sub(r"\([^()]*\)", "", token).strip()
    m = re.match(rf"^(.+?)\s*({_NUMBER})\s*([^\d]*)$", base)
    if m and not re.search(r"\d", m.group(3)):
        try:
            name, qty, unit = _clean_name(m.group(1)), parse_quantity(m.group(2)), m.group(3).strip()[:20]
        except ValueError:
            name = None
        if name:
            # 괄호가 여럿이면('황태(채) 15g(10개)') 숫자가 든 마지막 괄호를 본다.
            # '오이 70g(1/3개)' 처럼 개수가 1/2 가 아닌 소수(0.33개)로 나오면 g 이 더 읽기 쉬워 그대로 둔다.
            parens = [p for p in re.findall(r"\(([^()]*)\)", token) if re.search(r"\d", p)]
            home = _amount(parens[-1].split(",")[0]) if parens else None
            if home and home[0] is not None and home[1] in HOME_UNITS and (home[1] in HALF_UNITS or home[0] >= 1 or home[0] == 0.5):
                return name, home[0], home[1]
            return name, qty, unit
    words = base.split()
    if len(words) > 1 and words[-1] in NO_AMOUNT:
        return _clean_name(" ".join(words[:-1])), None, words[-1]
    if re.search(r"\d", base):  # 숫자가 섞였지만 형식을 알 수 없는 경우: 전체를 이름으로 두지 않고 뒤쪽을 단위 칸에
        m = re.match(r"^(\D+?)\s*(\d.*)$", base)
        if m:
            return _clean_name(m.group(1)), None, m.group(2).strip()[:20]
    return _clean_name(base), None, ""


def _clean_name(name):
    return re.sub(r"\s+", " ", name).strip(" :·-")[:40]


def _is_header(line, title):
    """'고명', '[양념장]', '새우두부계란찜' 처럼 재료가 아닌 소제목 줄"""
    plain = line.strip("[]<>()●•· :")
    if not plain:
        return True
    if plain.replace(" ", "") == (title or "").replace(" ", ""):
        return True
    return "," not in line and not re.search(r"\d", line) and not any(w in line for w in NO_AMOUNT)


def _round(qty, unit):
    """2/3작은술 같은 값은 0.67 처럼 보기 어려워서: 큰술·작은술 등은 0.5 단위, 그 밖은 소수 첫째 자리까지"""
    if qty is None:
        return None
    if unit in HALF_UNITS:
        return max(0.5, round(qty * 2) / 2)
    if qty < 1:
        return round(qty, 2)  # 3/4모 → 0.75모
    return round(qty, 1) if qty < 10 else round(qty)


def parse_parts(text, title=""):
    """재료 글 전체 → [{'name', 'quantity', 'unit'}], 그리고 글에 '[2인분]' 이 있으면 인분 수"""
    text = (text or "").replace("\r", "\n")
    servings = None
    m = re.search(r"(\d+)\s*인분", text)
    if m:
        servings = int(m.group(1))
    text = re.sub(r"[\[(<]?\s*\d+\s*인분\s*(?:기준)?\s*[\])>]?", "\n", text)
    out, seen = [], set()
    for line in text.split("\n"):
        line = line.strip()
        if ":" in line:  # '●주재료 : 연두부 75g, …' → 소제목 부분을 뗀다
            line = line.split(":", 1)[1].strip()
        if not line or _is_header(line, title):
            continue
        for token in _split_outside_parens(line):
            item = parse_ingredient(token)
            if not item or not item[0]:
                continue
            name, qty, unit = item
            if name in seen:  # 같은 재료가 두 번 적힌 경우(주재료·양념 양쪽) 첫 번째만
                continue
            seen.add(name)
            out.append({"name": name, "quantity": _round(qty, unit), "unit": unit})
    return out, servings


def clean_step(text):
    """'1. 손질한 새우를 끓는 물에 데친다.a' → '손질한 새우를 끓는 물에 데친다.'"""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    text = re.sub(r"^\d+\s*[.)]\s*", "", text)
    text = re.sub(r"(?<=[.다요])\s*[a-zA-Z]$", "", text)  # 원본 데이터 끝에 붙은 사진 번호 글자
    return text.strip()


def category_for(row):
    """API 분류(RCP_PAT2: 반찬·국&찌개·후식·일품·밥·기타) → 우리 분류"""
    name, pat, way = row.get("RCP_NM", ""), row.get("RCP_PAT2", ""), row.get("RCP_WAY2", "")
    if "샐러드" in name:
        return "샐러드"
    if any(w in name for w in ("국수", "파스타", "스파게티", "우동", "냉면", "라면", "칼국수", "쌀국수", "면")):
        return "면"
    simple = {"반찬": "반찬", "국&찌개": "국·탕·찌개", "후식": "간식·디저트", "밥": "밥·덮밥·볶음밥"}
    if pat in simple:
        return simple[pat]
    if any(w in name for w in ("밥", "죽", "리조또", "리소토")):
        return "밥·덮밥·볶음밥"
    if way in ("굽기", "찌기", "볶기"):
        return "구이·찜·볶음"
    return "기타"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def convert_row(row):
    """API 원본 한 건 → apply_recipe_data 에 넣을 dict. 재료나 조리 순서가 없으면 None."""
    title = re.sub(r"\s+", " ", row.get("RCP_NM") or "").strip()[:60]
    ingredients, servings = parse_parts(row.get("RCP_PARTS_DTLS"), title)
    steps = [clean_step(row.get(f"MANUAL{i:02d}")) for i in range(1, 21)]
    steps = [s for s in steps if s][:30]
    if not title or not ingredients or not steps:
        return None
    nutrition = {"열량": (_num(row.get("INFO_ENG")), "kcal"), "탄수화물": (_num(row.get("INFO_CAR")), "g"),
                 "단백질": (_num(row.get("INFO_PRO")), "g"), "지방": (_num(row.get("INFO_FAT")), "g"),
                 "나트륨": (_num(row.get("INFO_NA")), "mg")}
    return {
        "external_id": f"{SERVICE}:{row.get('RCP_SEQ')}",
        "title": title,
        "description": re.sub(r"\s+", " ", row.get("RCP_NA_TIP") or "").strip()[:500],
        "category": category_for(row),
        "servings": min(20, servings or 1),
        "cook_time_min": 0,   # API 에 조리 시간이 없다 → 0 = '시간 정보 없음' 으로 표시
        "ingredients": ingredients[:40],
        "steps": steps,
        "is_public": True,
        "info": {"source": SOURCE_NAME, "parser": PARSER_VERSION, "nutrition": {k: v for k, v in nutrition.items() if v[0] is not None}},
    }


# ---------- 3) 저장 ----------
def public_author():
    """공공 레시피 작성자 계정. 비밀번호는 아무도 모르는 임의 값이라 로그인할 수 없다."""
    user = db.session.scalar(db.select(User).filter_by(username=PUBLIC_USERNAME))
    if not user:
        user = User(username=PUBLIC_USERNAME, nickname=PUBLIC_NICKNAME)
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
        db.session.flush()
    return user


def import_rows(rows, batch=200, refresh=False):
    """원본 목록을 저장. (새로 넣은 수, 이미 있어 건너뛴 수, 형식이 맞지 않아 뺀 수, 다시 정리한 수)

    refresh=True 면 이미 있는 레시피도 지금 방식으로 재료·조리 순서를 다시 정리한다 (좋아요·즐겨찾기는 그대로).
    """
    author = public_author()
    existing = dict(db.session.execute(
        db.select(Recipe.external_id, Recipe.id).where(Recipe.external_id.is_not(None))).all())
    added = skipped = bad = refreshed = 0
    for row in rows:
        data = convert_row(row)
        if data is None:
            bad += 1
            continue
        info = json.dumps(data["info"], ensure_ascii=False)
        if data["external_id"] in existing:
            if not refresh:
                skipped += 1
                continue
            recipe = db.session.get(Recipe, existing[data["external_id"]])
            recipe.extra_info = info
            apply_recipe_data(recipe, data)
            refreshed += 1
        else:
            recipe = Recipe(author_id=author.id, origin="public", external_id=data["external_id"], extra_info=info)
            apply_recipe_data(recipe, data)
            db.session.add(recipe)
            db.session.flush()
            existing[data["external_id"]] = recipe.id
            added += 1
        if (added + refreshed) % batch == 0:
            db.session.commit()
    db.session.commit()
    return added, skipped, bad, refreshed


def outdated_count():
    """예전 방식(PARSER_VERSION 보다 낮음)으로 정리된 공공 레시피 수"""
    current = f'"parser": {PARSER_VERSION}'
    return db.session.scalar(db.select(db.func.count(Recipe.id)).where(
        Recipe.origin == "public", or_(Recipe.extra_info.is_(None), ~Recipe.extra_info.contains(current)))) or 0


def public_count():
    return db.session.scalar(db.select(db.func.count(Recipe.id)).where(Recipe.origin == "public")) or 0


def import_public_in_background(app, key):
    """서버 시작 때: 공공 레시피가 없으면 가져오고, 예전 방식으로 정리된 것이 있으면 다시 정리한다. 둘 다 아니면 아무것도 안 함."""
    with app.app_context():
        try:
            refresh = public_count() > 0
            if refresh and not outdated_count():
                return
            app.logger.warning("공공 레시피를 %s 중이에요…", "다시 정리하는" if refresh else "가져오는")
            added, skipped, bad, refreshed = import_rows(fetch_rows(key), refresh=refresh)
            app.logger.warning("공공 레시피 %d개 저장, %d개 다시 정리 (형식이 맞지 않아 뺌 %d)", added, refreshed, bad)
        except Exception as e:  # 가져오기에 실패해도 사이트는 그대로 동작해야 한다
            db.session.rollback()
            app.logger.warning("공공 레시피를 가져오지 못했어요: %s", e)
        finally:
            db.session.remove()
