"""학교 → 역 방향 '하교 셔틀' 시간표와, 모임이 끝난 뒤 탈 수 있는 셔틀을 판정하는 모듈.

시간표 출처: 셔틀버스 예약 시스템 조사 보고서의 '학교 → 역' 행 (2026학년도 기준).
다른 학교에 쓰려면 이 파일의 TIMETABLE 만 바꾸면 된다.
"""
from datetime import date, datetime, time

try:  # 공휴일에는 셔틀이 운행하지 않는다 (예약 시스템과 같은 holidays 패키지 사용)
    import holidays
    KR_HOLIDAYS = holidays.country_holidays("KR")
except Exception:  # 패키지가 없으면 공휴일 판정만 건너뛰고 주말만 제외한다
    KR_HOLIDAYS = {}

WEEK = "월화수목금토일"

# 모임이 끝난 뒤 셔틀 타는 곳까지 이동할 시간(분). 이보다 여유가 적으면 '빠듯함'으로 본다.
WALK_BUFFER_MIN = 10

# (노선, 출발 시각, 월~목 운행 여부, 금 운행 여부) - 토·일·공휴일은 운행하지 않는다
TIMETABLE = [
    ("도봉산역", "16:30", True, False),
    ("도봉산역", "17:30", True, True),
    ("도봉산역", "18:30", True, False),
    ("의정부중앙역", "14:00", True, False),
    ("의정부중앙역", "15:00", True, False),
    # 양주역 (학교 정문 앞 출발 → 덕현초교·덕고개 잠시 정차 → 양주역), 학교 홈페이지 시간표 기준
    ("양주역", "13:30", True, False),
    ("양주역", "14:00", True, False),
    ("양주역", "14:30", True, False),
    ("양주역", "15:30", True, False),
    ("양주역", "16:10", True, False),
    ("양주역", "17:00", True, False),
    ("양주역", "17:40", False, True),
    ("양주역", "17:45", True, False),
    ("양주역", "18:30", True, True),      # 옥정 경유 (막차)
]

ROUTES = ["도봉산역", "양주역", "의정부중앙역"]

STYLE = {  # 상태별 색(Tailwind 클래스)과 아이콘
    "ok":     {"cls": "bg-emerald-100 text-emerald-700", "icon": "✅"},
    "tight":  {"cls": "bg-amber-100 text-amber-700",     "icon": "⚠️"},
    "missed": {"cls": "bg-rose-100 text-rose-700",       "icon": "❌"},
    "none":   {"cls": "bg-slate-100 text-slate-500",     "icon": "🚫"},
}


def _hm(text):
    h, m = text.split(":")
    return time(int(h), int(m))


def service_kind(day):
    """'mon_thu' | 'fri' | None (주말·공휴일은 운행 없음)"""
    if day.weekday() >= 5 or day in KR_HOLIDAYS:
        return None
    return "fri" if day.weekday() == 4 else "mon_thu"


def departures(route, day):
    """그날 해당 노선의 하교 출발 시각 목록(오름차순). 운행이 없으면 빈 목록."""
    kind = service_kind(day)
    if kind is None:
        return []
    return sorted(_hm(t) for r, t, mon_thu, fri in TIMETABLE
                  if r == route and (mon_thu if kind == "mon_thu" else fri))


def last_departure(route, day):
    """그날 해당 노선의 막차 시각. 운행이 없으면 None."""
    deps = departures(route, day)
    return deps[-1] if deps else None


def _span(minutes):
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h and m else (f"{h}시간" if h else f"{m}분")


def _no_service_reason(day):
    holiday = KR_HOLIDAYS.get(day)
    if holiday:
        return holiday
    if day.weekday() >= 5:
        return f"{WEEK[day.weekday()]}요일"
    return f"{WEEK[day.weekday()]}요일 미운행"


def _result(route, status, last, slack, text):
    return {"route": route, "status": status, "last": last, "slack": slack,
            "text": text, **STYLE[status]}


def check(route, meet, end):
    """모임(meet ~ end)이 끝난 뒤 탈 수 있는 가장 빠른 셔틀을 찾는다.

    - ok     : 종료 후 이동 시간(WALK_BUFFER_MIN) 이상 여유를 두고 탈 수 있는 가장 빠른 셔틀이 있음
    - tight  : 그날 셔틀이 남았지만 모두 종료 후 이동 시간 안에 출발함 (서둘러야 함)
    - missed : 종료 시각 이후에 출발하는 셔틀이 없음 (막차를 놓침)
    - none   : 주말·공휴일 등 그날 셔틀이 없음
    """
    day = meet.date()
    deps = departures(route, day)
    if not deps:
        return _result(route, "none", None, None, f"셔틀 없음 ({_no_service_reason(day)})")

    def gap(dep):  # 종료 시각 → 출발까지 걸리는 분
        return int((datetime.combine(day, dep) - end).total_seconds() // 60)

    comfortable = [d for d in deps if gap(d) >= WALK_BUFFER_MIN]
    if comfortable:
        d = comfortable[0]
        return _result(route, "ok", f"{d:%H:%M}", gap(d), f"가장 빠른 셔틀 {d:%H:%M} · 종료 후 {_span(gap(d))}")
    after = [d for d in deps if gap(d) >= 0]
    if after:
        d = after[0]
        return _result(route, "tight", f"{d:%H:%M}", gap(d), f"{d:%H:%M} 셔틀이 종료 후 {gap(d)}분뿐이에요")
    return _result(route, "missed", f"{deps[-1]:%H:%M}", gap(deps[-1]), f"막차 {deps[-1]:%H:%M} 이후에 끝나요")


def check_all(meet, end):
    return [check(r, meet, end) for r in ROUTES]
