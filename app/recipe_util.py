"""레시피 공용 도구: 재료량 표시, 등록·수정 폼 검증, 재료 이름 정리.

재료량 표시 규칙은 static/app.js 의 rmQuantity() 와 같다 (상세 화면에서 인분을 바꿀 때 브라우저가 다시 계산).
"""
import re

from .models import CATEGORIES

# 쪼갤 수 없는 단위는 4.5개 대신 '4~5개', 반으로 나누는 단위는 0.5 단위, g·ml 는 정수로 보여 준다
WHOLE_UNITS = {"개", "알", "마리", "모", "캔", "봉", "봉지"}
HALF_UNITS = {"공기", "대", "장", "쪽", "송이", "줄기", "컵", "큰술", "작은술", "줌"}

MAX_INGREDIENTS = 40
MAX_STEPS = 30
MAX_SERVINGS = 20


def _plain(v):
    v = round(v, 3)
    if v == 0.5:
        return "1/2"
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def format_quantity(quantity, unit, factor=1.0):
    """수량을 화면용 문자열로. 수량이 없으면('약간') 빈 문자열."""
    if quantity is None:
        return ""
    if factor == 1:
        return _plain(quantity)
    v = round(quantity * factor, 3)
    if unit in WHOLE_UNITS:
        if float(v).is_integer():
            return str(int(v))
        lo, hi = max(1, int(v)), int(v) + 1
        return str(hi) if lo == hi else f"{lo}~{hi}"
    if unit in HALF_UNITS:
        h = max(0.5, round(v * 2) / 2)
        return _plain(h)
    if unit in ("g", "ml"):
        return str(max(1, round(v)))
    return f"{round(v, 1):g}"


def format_amount(quantity, unit, factor=1.0):
    return f"{format_quantity(quantity, unit, factor)}{unit}"


def parse_quantity(text):
    """'2', '0.5', '1/2', '1 1/2' → float. 빈 값 → None. 숫자가 아니면 ValueError."""
    text = (text or "").strip()
    if not text:
        return None
    m = re.fullmatch(r"(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)", text)
    if m:
        whole, num, den = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
        if den == 0:
            raise ValueError
        return whole + num / den
    v = float(text)
    if v < 0 or v != v or v > 100000:
        raise ValueError
    return v


def normalize_name(name):
    """재료 이름 비교용: 공백 제거 + 같은 재료의 다른 이름 통일 (계란 → 달걀)."""
    n = re.sub(r"\s+", "", name or "")
    return ALIASES.get(n, n)


ALIASES = {"계란": "달걀", "에그": "달걀", "파": "대파", "파스타면": "스파게티면", "쌀밥": "밥", "흰밥": "밥"}
COMMON_INGREDIENTS = [
    "달걀", "감자", "고구마", "김치", "당근", "대파", "쪽파", "두부", "마늘", "밥", "버섯", "설탕", "소금", "식용유",
    "양파", "우유", "치즈", "토마토", "방울토마토", "간장", "국수", "들기름", "김", "올리브유", "닭고기", "돼지고기",
    "소고기", "고추장", "된장", "참기름", "후추", "소면", "고춧가루", "애호박", "파프리카", "버터", "베이컨", "햄",
    "참치캔", "스팸", "어묵", "떡", "라면", "스파게티면", "생크림", "양배추", "상추", "오이", "깻잎", "청양고추",
]


def parse_recipe_form(form):
    """등록·수정 폼 → (data, errors). 화면의 입력 제한은 우회될 수 있으므로 서버에서 다시 검사한다."""
    errors = []
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "")
    if not 1 <= len(title) <= 60:
        errors.append("요리 이름을 1~60자로 입력해 주세요.")
    if len(description) > 1000:
        errors.append("설명은 1000자 이내로 입력해 주세요.")
    if category not in CATEGORIES:
        errors.append("요리 종류를 골라 주세요.")
    servings = cook_time = None
    try:
        servings = int(form.get("servings", ""))
        if not 1 <= servings <= MAX_SERVINGS:
            raise ValueError
    except ValueError:
        errors.append(f"인분은 1~{MAX_SERVINGS} 사이의 숫자로 입력해 주세요.")
    try:
        cook_time = int(form.get("cook_time_min", ""))
        if not 1 <= cook_time <= 600:
            raise ValueError
    except ValueError:
        errors.append("조리 시간은 1~600분 사이의 숫자로 입력해 주세요.")

    names, qtys, units = form.getlist("ing_name"), form.getlist("ing_qty"), form.getlist("ing_unit")
    ingredients = []
    for i, name in enumerate(names):
        name = name.strip()
        qty_text = qtys[i].strip() if i < len(qtys) else ""
        unit = units[i].strip() if i < len(units) else ""
        if not name and not qty_text and not unit:
            continue  # 비워 둔 줄은 무시
        if not 1 <= len(name) <= 40:
            errors.append(f"{i + 1}번째 재료의 이름을 1~40자로 입력해 주세요.")
            continue
        try:
            qty = parse_quantity(qty_text)
        except ValueError:
            # '약간', '적당량' 처럼 숫자가 아닌 수량은 단위 칸에 그대로 둔다
            if unit:
                errors.append(f"{name}: 수량은 숫자(예: 2, 0.5, 1/2)로 입력해 주세요.")
                continue
            qty, unit = None, qty_text
        if len(unit) > 20:
            errors.append(f"{name}: 단위는 20자 이내로 입력해 주세요.")
            continue
        ingredients.append({"name": name, "quantity": qty, "unit": unit})
    if not ingredients:
        errors.append("재료를 한 개 이상 입력해 주세요.")
    if len(ingredients) > MAX_INGREDIENTS:
        errors.append(f"재료는 {MAX_INGREDIENTS}개까지 입력할 수 있어요.")

    steps = [s.strip() for s in form.getlist("step") if s.strip()]
    if not steps:
        errors.append("조리 순서를 한 단계 이상 입력해 주세요.")
    if len(steps) > MAX_STEPS:
        errors.append(f"조리 순서는 {MAX_STEPS}단계까지 입력할 수 있어요.")
    if any(len(s) > 500 for s in steps):
        errors.append("조리 순서 한 단계는 500자 이내로 입력해 주세요.")

    data = {
        "title": title, "description": description, "category": category,
        "servings": servings, "cook_time_min": cook_time,
        "ingredients": ingredients, "steps": steps,
        "is_public": form.get("visibility", "public") == "public",
    }
    return data, errors
