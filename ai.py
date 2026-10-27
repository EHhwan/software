"""'한 줄로 번개 만들기': 자연어 한 문장을 Gemini 가 읽고 작성 폼에 채울 값을 뽑아 주는 모듈.

예) "내일 수업 끝나고 6시쯤 체육관에서 배드민턴 3명, 1시간 반 정도"
 → 제목·카테고리·시작 시각·소요 시간·인원·장소

AI 답은 그대로 믿지 않는다. 형식이 틀리거나 허용 범위를 벗어난 값은 버리고(None),
사용자가 폼에서 직접 고르게 한다. 글 등록은 항상 사용자가 확인한 뒤 기존 /new 검증을 거친다.
"""
import json
import os
from datetime import datetime, timedelta

WEEK = "월화수목금토일"
FMT_AI = "%Y-%m-%d %H:%M"
MAX_DAYS_AHEAD = 30   # 이보다 먼 날짜는 잘못 읽은 것으로 보고 버린다
TIMEOUT_SEC = 8       # Gemini 응답을 기다리는 최대 시간

_model = None


class AIUnavailable(Exception):
    """API 키가 없거나, 응답이 없거나, 응답을 읽을 수 없을 때."""


def _get_model():
    global _model
    if _model is None:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise AIUnavailable("GEMINI_API_KEY 가 설정되지 않았어요.")
        import google.generativeai as genai  # 키가 있을 때만 불러온다 (없어도 나머지 서비스는 동작)
        genai.configure(api_key=key)
        _model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    return _model


def build_prompt(text, now, categories, durations):
    """역할 + 기준 시각 + 허용 값 + 출력 형식을 지시문으로 묶고, 사용자 문장은 맨 끝에 데이터로 붙인다."""
    return f"""너는 대학생 '번개 모임' 글 작성 도우미야.
사용자가 쓴 한 문장에서 모임 정보를 뽑아 JSON 하나로만 답해. 설명이나 다른 말은 하지 마.

[기준 시각] {now:%Y-%m-%d %H:%M} ({WEEK[now.weekday()]}요일, 한국 시간)
"오늘/내일/모레/금요일/이따/수업 끝나고" 같은 표현은 이 기준 시각으로 계산해.
"6시"처럼 오전·오후가 없으면 대학생 모임으로 자연스러운 쪽(보통 오후)으로 정해.
"지금", "바로"는 기준 시각 5분 뒤로 정해.

[출력 형식]
{{
  "title": "모임을 한눈에 알 수 있는 제목, 2~40자",
  "category": {json.dumps(categories, ensure_ascii=False)} 중 하나,
  "meet_time": "YYYY-MM-DD HH:MM",
  "duration_min": {[m for m, _ in durations]} 중 문장에 가장 가까운 값,
  "max_people": 방장 포함 전체 인원 (2~50 정수),
  "location": "모이는 장소, 40자 이내",
  "description": "문장에 있는 준비물·조건 등 추가 정보, 100자 이내 (없으면 빈 문자열)"
}}
문장에서 알 수 없는 값은 지어내지 말고 null 로 둬.
"3명 구해요"처럼 '구하는 사람 수'만 있으면 방장을 더해 max_people 로 써.

[사용자 문장]
{text}"""


def _ask_gemini(prompt):
    try:
        res = _get_model().generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json", "temperature": 0.2},
            request_options={"timeout": TIMEOUT_SEC},
        )
        return json.loads(res.text)
    except AIUnavailable:
        raise
    except Exception as e:  # 네트워크 오류, 시간 초과, 할당량 초과, 안전 차단, JSON 깨짐 등
        raise AIUnavailable(str(e)) from e


def _clean_text(value, max_len, min_len=1):
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())[:max_len]
    return value if len(value) >= min_len else None


def validate(raw, now, categories, durations):
    """Gemini 답을 검증해서 폼에 넣어도 되는 값만 남긴다. 잘못된 값은 None."""
    if not isinstance(raw, dict):
        raise AIUnavailable("AI 답이 JSON 객체가 아니에요.")
    now = now.replace(second=0, microsecond=0)
    out = {
        "title": _clean_text(raw.get("title"), 40, min_len=2),
        "category": raw.get("category") if raw.get("category") in categories else None,
        "location": _clean_text(raw.get("location"), 40),
        "description": _clean_text(raw.get("description"), 300) or "",
        "meet_time": None,
        "duration": None,
        "max_people": None,
    }
    try:  # 지난 시각이거나 너무 먼 날짜는 잘못 읽은 것으로 본다
        meet = datetime.strptime(str(raw.get("meet_time")), FMT_AI)
        if now <= meet <= now + timedelta(days=MAX_DAYS_AHEAD):
            out["meet_time"] = meet.strftime("%Y-%m-%dT%H:%M")  # <input type="datetime-local"> 형식
    except ValueError:
        pass
    try:  # 목록에 없는 값이면 가장 가까운 선택지로 맞춘다
        minutes = int(raw.get("duration_min"))
        if minutes > 0:
            out["duration"] = min((m for m, _ in durations), key=lambda m: abs(m - minutes))
    except (TypeError, ValueError):
        pass
    try:
        people = int(raw.get("max_people"))
        if 2 <= people <= 50:
            out["max_people"] = people
    except (TypeError, ValueError):
        pass
    return out


def draft_post(text, now, categories, durations):
    """문장 → 폼에 채울 값(dict). 실패하면 AIUnavailable."""
    raw = _ask_gemini(build_prompt(text, now, categories, durations))
    return validate(raw, now, categories, durations)
