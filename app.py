import hmac
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import shuttle  # 하교 셔틀 시간표 + '끝난 뒤 탈 셔틀' 판정

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-campus-fit-change-me")
app.permanent_session_lifetime = timedelta(days=30)
# 다른 사이트에서 보낸 POST 요청에는 세션 쿠키가 실리지 않게 한다 (CSRF 1차 방어)
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

DATABASE = os.environ.get("CAMPUS_FIT_DB", os.path.join(app.root_path, "campus_fit.db"))
# 카카오 developers > 내 애플리케이션 > 'JavaScript 키' (REST API 키 아님)
KAKAO_JS_KEY = os.environ.get("KAKAO_JS_KEY", "69c470f70da3ed4598a91bbd6c8557ab")

CATEGORIES = ["스포츠", "공부", "식사", "헬스", "기타"]
TABS = ["전체"] + CATEGORIES
CAT_META = {
    "스포츠": {"emoji": "⚽", "cls": "bg-sky-100 text-sky-700", "ring": "peer-checked:bg-sky-500 peer-checked:text-white"},
    "공부":   {"emoji": "📚", "cls": "bg-amber-100 text-amber-700", "ring": "peer-checked:bg-amber-500 peer-checked:text-white"},
    "식사":   {"emoji": "🍔", "cls": "bg-rose-100 text-rose-700", "ring": "peer-checked:bg-rose-500 peer-checked:text-white"},
    "헬스":   {"emoji": "💪", "cls": "bg-emerald-100 text-emerald-700", "ring": "peer-checked:bg-emerald-500 peer-checked:text-white"},
    "기타":   {"emoji": "✨", "cls": "bg-violet-100 text-violet-700", "ring": "peer-checked:bg-violet-500 peer-checked:text-white"},
}
STATUS_META = {
    "open":   {"label": "모집 중",   "cls": "bg-emerald-500 text-white"},
    "full":   {"label": "모집 완료", "cls": "bg-violet-500 text-white"},
    "closed": {"label": "마감됨",    "cls": "bg-slate-400 text-white"},
}
WEEK = "월화수목금토일"
FMT_DB = "%Y-%m-%d %H:%M"
FMT_INPUT = "%Y-%m-%dT%H:%M"

# 글 작성 시 고르는 예상 소요 시간 (분, 화면에 보일 이름)
DURATIONS = [(30, "30분"), (60, "1시간"), (90, "1시간 30분"), (120, "2시간"), (180, "3시간"), (240, "4시간")]
DURATION_LABEL = dict(DURATIONS)
DEFAULT_DURATION = 60

LOCK_AFTER = 5        # 비밀번호를 이 횟수만큼 틀리면
LOCK_SECONDS = 300    # 이 시간(초) 동안 잠금
CLOSED_LIMIT = 20     # 목록에는 마감된 글을 최근 순으로 이 개수까지만 표시

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT    NOT NULL,
    category       TEXT    NOT NULL,
    description    TEXT    NOT NULL DEFAULT '',
    location       TEXT    NOT NULL DEFAULT '',
    address        TEXT    NOT NULL DEFAULT '',  -- 카카오 지도에서 찾은 주소
    lat            REAL,
    lng            REAL,
    meet_time      TEXT    NOT NULL,  -- 'YYYY-MM-DD HH:MM'
    duration_min   INTEGER NOT NULL DEFAULT 60,  -- 예상 소요 시간(분): 끝나는 시각 = meet_time + duration_min
    max_people     INTEGER NOT NULL,
    current_people INTEGER NOT NULL DEFAULT 1,
    password_hash  TEXT    NOT NULL,
    closed_early   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_meet ON posts(meet_time);

-- 글마다 '참여한 브라우저(uid)'를 한 번만 기록: 연타·동시 요청에도 중복 집계되지 않게 한다
CREATE TABLE IF NOT EXISTS participants (
    post_id  INTEGER NOT NULL,
    uid      TEXT    NOT NULL,
    is_owner INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (post_id, uid)
);

-- 비밀번호 오입력 기록(글 + 접속지 단위)
CREATE TABLE IF NOT EXISTS pw_fails (
    post_id      INTEGER NOT NULL,
    ip           TEXT    NOT NULL,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    locked_until REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (post_id, ip)
);
"""


# ---------- DB ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=15)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript(SCHEMA)
    # 이미 만들어진 DB(주소 컬럼 없음)도 그대로 쓸 수 있게 마이그레이션
    cols = {r[1] for r in db.execute("PRAGMA table_info(posts)")}
    if "address" not in cols:
        db.execute("ALTER TABLE posts ADD COLUMN address TEXT NOT NULL DEFAULT ''")
    if "duration_min" not in cols:  # 예전 글은 1시간짜리로 본다
        db.execute("ALTER TABLE posts ADD COLUMN duration_min INTEGER NOT NULL DEFAULT 60")
    db.commit()
    db.close()


# ---------- 상태/시간 계산 ----------
def compute_status(row, now):
    meet = datetime.strptime(row["meet_time"], FMT_DB)
    if row["closed_early"] or meet < now:
        return "closed"
    if row["current_people"] >= row["max_people"]:  # current_people == max_people
        return "full"
    return "open"


def day_label(day, today):
    diff = (day - today).days
    if diff == 0:
        return "오늘"
    if diff == 1:
        return "내일"
    return f"{day:%m/%d}({WEEK[day.weekday()]})"


def time_label(meet, now):
    return f"{day_label(meet.date(), now.date())} {meet:%H:%M}"


def end_label(meet, end):
    """끝나는 시각 표시. 다음 날로 넘어가면 '익일'을 붙인다."""
    return f"{'익일 ' if end.date() != meet.date() else ''}{end:%H:%M}"


def remaining_label(meet, now):
    # now 는 enrich() 에서 '분 단위'로 내림한 값이라, 모임 시각과 같은 분이면 sec == 0
    sec = int((meet - now).total_seconds())
    if sec < 0:
        return "종료"
    if sec == 0:
        return "지금 시작"
    m = sec // 60
    if m < 60:
        return f"{m}분 후"
    h, mm = divmod(m, 60)
    if h < 24:
        return f"{h}시간 {mm}분 후" if mm else f"{h}시간 후"
    return f"{h // 24}일 후"


def enrich(row, now):
    # 모임 시각은 분 단위로 저장되므로 판정도 분 단위로 통일한다.
    # (같은 분 안에서는 '마감'이 아니라 '진행 중'이고, 참여 가능 여부(join)와도 일치)
    now = now.replace(second=0, microsecond=0)
    p = dict(row)
    meet = datetime.strptime(p["meet_time"], FMT_DB)
    p["status"] = compute_status(row, now)
    p["status_label"] = STATUS_META[p["status"]]["label"]
    p["badge_cls"] = STATUS_META[p["status"]]["cls"]
    p["time_label"] = time_label(meet, now)
    p["remaining"] = remaining_label(meet, now)
    # 끝나는 시각 = 모임 시각 + 예상 소요 시간 (셔틀 판정에 사용)
    minutes = p.get("duration_min") or DEFAULT_DURATION
    p["meet"] = meet
    p["end"] = meet + timedelta(minutes=minutes)
    p["end_label"] = end_label(meet, p["end"])
    p["duration_label"] = DURATION_LABEL.get(minutes, f"{minutes}분")
    minutes_left = (meet - now).total_seconds() / 60
    p["urgent"] = p["status"] == "open" and minutes_left <= 60
    p["percent"] = min(100, int(p["current_people"] / p["max_people"] * 100))
    p["cat"] = CAT_META.get(p["category"], CAT_META["기타"])
    p["ts"] = meet.timestamp()
    return p


@app.context_processor
def inject_globals():
    return {"TABS": TABS, "CATEGORIES": CATEGORIES, "CAT_META": CAT_META,
            "KAKAO_JS_KEY": KAKAO_JS_KEY, "csrf_token": csrf_token,
            "ROUTES": shuttle.ROUTES, "DURATIONS": DURATIONS,
            "SHUTTLE_BUFFER": shuttle.WALK_BUFFER_MIN}


# ---------- 세션 식별(uid) + CSRF ----------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def _identify_and_check_csrf():
    # 로그인이 없으므로 브라우저마다 랜덤 uid 를 발급해 '같은 사람'을 구분한다
    if "uid" not in session:
        session["uid"] = secrets.token_hex(16)
        session.permanent = True
    if request.method == "POST":
        sent = request.form.get("csrf_token", "").encode()
        good = session.get("csrf", "").encode()
        if not good or not hmac.compare_digest(sent, good):
            flash("요청이 만료됐어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.", "error")
            return redirect(url_for("index"))


def parse_coords(form):
    """지도에서 넘어온 lat/lng를 검증한다. 올바르지 않으면 (None, None)."""
    try:
        lat = float(form.get("lat", "").strip())
        lng = float(form.get("lng", "").strip())
    except ValueError:
        return None, None
    if not (32.0 <= lat <= 39.5 and 123.0 <= lng <= 132.5):  # 대한민국 범위
        return None, None
    return lat, lng


def _participant(post_id):
    """이 브라우저가 해당 글의 참여자이면 행(is_owner 포함), 아니면 None."""
    return get_db().execute(
        "SELECT is_owner FROM participants WHERE post_id = ? AND uid = ?",
        (post_id, session["uid"]),
    ).fetchone()


# ---------- 라우트 ----------
@app.route("/")
def index():
    category = request.args.get("category", "전체")
    if category not in TABS:
        category = "전체"
    only_open = request.args.get("open") == "1"

    # 내가 타는 셔틀 노선: 한 번 고르면 기억해 두고, route= (빈 값)으로 '선택 안 함'
    if "route" in request.args:
        session["route"] = request.args["route"] if request.args["route"] in shuttle.ROUTES else ""
    route = session.get("route", "")
    if route not in shuttle.ROUTES:
        route = ""
    last_only = request.args.get("last") == "1" and bool(route)  # 노선을 골라야 셔틀 필터를 쓸 수 있다

    now = datetime.now()
    now_min = now.replace(second=0, microsecond=0).strftime(FMT_DB)
    cat_sql, cat_args = ("", []) if category == "전체" else (" AND category = ?", [category])
    db = get_db()

    # 진행 중(모집 중/모집 완료) 글은 전부, 마감된 글은 최근 CLOSED_LIMIT 개만 가져온다
    rows = db.execute(
        "SELECT * FROM posts WHERE closed_early = 0 AND meet_time >= ?" + cat_sql,
        [now_min] + cat_args,
    ).fetchall()
    if not only_open:
        rows += db.execute(
            "SELECT * FROM posts WHERE (closed_early = 1 OR meet_time < ?)" + cat_sql +
            " ORDER BY meet_time DESC LIMIT ?",
            [now_min] + cat_args + [CLOSED_LIMIT],
        ).fetchall()

    posts = [enrich(r, now) for r in rows]
    if only_open:
        posts = [p for p in posts if p["status"] == "open"]

    if route:
        # 지난 모임은 셔틀 정보가 의미 없으므로 계산하지 않는다
        for p in posts:
            if p["status"] != "closed":
                p["shuttle"] = shuttle.check(route, p["meet"], p["end"])
        if last_only:  # 셔틀을 여유 있게 탈 수 있는 번개만 (주말·공휴일처럼 셔틀이 없는 날도 제외)
            posts = [p for p in posts if p.get("shuttle") and p["shuttle"]["status"] == "ok"]

    rank = {"open": 0, "full": 1, "closed": 2}
    # 모집 중/완료는 임박한 순, 마감된 글은 맨 아래(최근 마감 순)
    posts.sort(key=lambda p: (rank[p["status"]], p["ts"] if p["status"] != "closed" else -p["ts"]))
    return render_template("index.html", posts=posts, category=category, only_open=only_open,
                           closed_limit=CLOSED_LIMIT, route=route, last_only=last_only)


@app.route("/new", methods=["GET", "POST"])
def new_post():
    now = datetime.now()
    default_time = (now + timedelta(minutes=5))  # '지금 바로'와 같은 기본값: 시작 5분 뒤.replace(second=0, microsecond=0)
    ctx = {
        "min_time": now.strftime(FMT_INPUT),
        "default_time": default_time.strftime(FMT_INPUT),
        "form": request.form,
    }
    if request.method == "GET":
        return render_template("new.html", **ctx)

    f = request.form
    title = f.get("title", "").strip()
    category = f.get("category", "")
    location = f.get("location", "").strip()
    description = f.get("description", "").strip()
    password = f.get("password", "").strip()
    address = f.get("address", "").strip()[:100]
    lat, lng = parse_coords(f)
    if lat is None:
        address = ""
    errors = []

    if not (2 <= len(title) <= 40):
        errors.append("제목은 2~40자로 입력해 주세요.")
    if category not in CATEGORIES:
        errors.append("카테고리를 선택해 주세요.")
    if not location:
        errors.append("모이는 장소를 입력해 주세요.")
    elif len(location) > 40:
        errors.append("모이는 장소는 40자 이내로 입력해 주세요.")
    if len(description) > 300:
        errors.append("설명은 300자 이내로 입력해 주세요.")
    try:
        meet = datetime.strptime(f.get("meet_time", ""), FMT_INPUT)
        if meet < now.replace(second=0, microsecond=0):
            errors.append("이미 지난 시간으로는 모임을 만들 수 없어요.")
    except ValueError:
        meet = None
        errors.append("모임 시간을 올바르게 입력해 주세요.")
    try:
        max_people = int(f.get("max_people", ""))
        if not 2 <= max_people <= 50:
            raise ValueError
    except ValueError:
        max_people = None
        errors.append("모집 인원은 방장 포함 2~50명으로 입력해 주세요.")
    try:
        duration = int(f.get("duration", DEFAULT_DURATION))
        if duration not in DURATION_LABEL:
            raise ValueError
    except ValueError:
        duration = None
        errors.append("예상 소요 시간을 목록에서 골라 주세요.")
    if not re.fullmatch(r"\d{4}", password):
        errors.append("비밀번호는 숫자 4자리여야 해요.")

    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("new.html", **ctx), 400

    db = get_db()
    cur = db.execute(
        """INSERT INTO posts (title, category, description, location, address, lat, lng,
                              meet_time, duration_min, max_people, current_people, password_hash, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (title, category, description, location, address, lat, lng, meet.strftime(FMT_DB), duration,
         max_people, generate_password_hash(password), now.strftime("%Y-%m-%d %H:%M:%S")),
    )
    post_id = cur.lastrowid
    # 방장은 자동 참여 (현재 인원 1명)
    db.execute("INSERT INTO participants (post_id, uid, is_owner) VALUES (?, ?, 1)",
               (post_id, session["uid"]))
    db.commit()
    flash("번개 모임이 만들어졌어요! ⚡ 삭제·조기마감용 비밀번호를 꼭 기억해 두세요.", "ok")
    return redirect(url_for("detail", post_id=post_id))


def _get_post_or_404(post_id):
    row = get_db().execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        abort(404)
    return row


@app.route("/post/<int:post_id>")
def detail(post_id):
    row = _get_post_or_404(post_id)
    p = enrich(row, datetime.now())
    if p["status"] != "closed":  # 노선별 셔틀 안내 (지난 모임은 생략)
        p["shuttle_all"] = shuttle.check_all(p["meet"], p["end"])
    me = _participant(post_id)
    return render_template(
        "detail.html", p=p,
        joined=me is not None, is_mine=bool(me and me["is_owner"]),
    )


@app.post("/post/<int:post_id>/join")
def join(post_id):
    _get_post_or_404(post_id)
    db = get_db()
    # 1) (글, 브라우저) 조합은 기본키라 한 번만 들어간다 → 연타·동시 요청이 와도 1명으로만 집계
    cur = db.execute(
        "INSERT OR IGNORE INTO participants (post_id, uid, is_owner) VALUES (?, ?, 0)",
        (post_id, session["uid"]),
    )
    if cur.rowcount == 0:
        db.rollback()
        flash("이미 참여 중이에요.", "error")
        return redirect(url_for("detail", post_id=post_id))
    # 2) 인원 초과·조기마감·시간 경과를 한 번의 UPDATE로 원자적으로 막는다 (분 단위 기준)
    cur = db.execute(
        """UPDATE posts SET current_people = current_people + 1
           WHERE id = ? AND current_people < max_people
             AND closed_early = 0 AND meet_time >= ?""",
        (post_id, datetime.now().replace(second=0, microsecond=0).strftime(FMT_DB)),
    )
    if cur.rowcount:
        db.commit()
        flash("참여 완료! 늦지 않게 나와요 🏃", "ok")
    else:
        db.rollback()  # 참여자 기록도 함께 취소
        flash("아쉽지만 지금은 참여할 수 없는 모임이에요.", "error")
    return redirect(url_for("detail", post_id=post_id))


@app.post("/post/<int:post_id>/leave")
def leave(post_id):
    _get_post_or_404(post_id)
    db = get_db()
    cur = db.execute(
        "DELETE FROM participants WHERE post_id = ? AND uid = ? AND is_owner = 0",
        (post_id, session["uid"]),
    )
    if not cur.rowcount:
        db.rollback()
        flash("참여 취소를 할 수 없어요. (방장은 글 삭제나 조기마감을 이용해 주세요)", "error")
        return redirect(url_for("detail", post_id=post_id))
    db.execute("UPDATE posts SET current_people = MAX(1, current_people - 1) WHERE id = ?", (post_id,))
    db.commit()
    flash("참여를 취소했어요.", "ok")
    return redirect(url_for("detail", post_id=post_id))


def check_password(row):
    """비밀번호를 확인한다. 반환: (성공 여부, 실패 시 안내 문구).
    글 + 접속지 단위로 LOCK_AFTER 회 틀리면 LOCK_SECONDS 동안 잠근다.
    동시에 여러 번 시도해도 횟수가 어긋나지 않도록 쓰기 잠금 안에서 처리한다."""
    db = get_db()
    ip = request.remote_addr or "?"
    now = time.time()
    db.execute("BEGIN IMMEDIATE")
    f = db.execute("SELECT fail_count, locked_until FROM pw_fails WHERE post_id = ? AND ip = ?",
                   (row["id"], ip)).fetchone()
    if f and f["locked_until"] > now:
        db.rollback()
        wait = int(f["locked_until"] - now) // 60 + 1
        return False, f"비밀번호를 {LOCK_AFTER}회 틀려 잠겼어요. 약 {wait}분 뒤에 다시 시도해 주세요."
    if check_password_hash(row["password_hash"], request.form.get("password", "").strip()):
        db.execute("DELETE FROM pw_fails WHERE post_id = ? AND ip = ?", (row["id"], ip))
        db.commit()
        return True, ""
    fails = (f["fail_count"] if f else 0) + 1
    if fails >= LOCK_AFTER:
        db.execute("INSERT OR REPLACE INTO pw_fails VALUES (?, ?, 0, ?)", (row["id"], ip, now + LOCK_SECONDS))
        msg = f"비밀번호를 {LOCK_AFTER}회 틀려 {LOCK_SECONDS // 60}분간 잠겼어요."
    else:
        db.execute("INSERT OR REPLACE INTO pw_fails VALUES (?, ?, ?, 0)", (row["id"], ip, fails))
        msg = f"비밀번호가 맞지 않아요. ({LOCK_AFTER - fails}회 남음)"
    db.commit()
    return False, msg


@app.post("/post/<int:post_id>/close")
def close_early(post_id):
    row = _get_post_or_404(post_id)
    ok, msg = check_password(row)
    if not ok:
        flash(msg, "error")
        return redirect(url_for("detail", post_id=post_id))
    db = get_db()
    db.execute("UPDATE posts SET closed_early = 1 WHERE id = ?", (post_id,))
    db.commit()
    flash("모집을 조기 마감했어요.", "ok")
    return redirect(url_for("detail", post_id=post_id))


@app.post("/post/<int:post_id>/delete")
def delete(post_id):
    row = _get_post_or_404(post_id)
    ok, msg = check_password(row)
    if not ok:
        flash(msg, "error")
        return redirect(url_for("detail", post_id=post_id))
    db = get_db()
    db.execute("DELETE FROM participants WHERE post_id = ?", (post_id,))
    db.execute("DELETE FROM pw_fails WHERE post_id = ?", (post_id,))
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    db.commit()
    flash("글을 삭제했어요.", "ok")
    return redirect(url_for("index"))


@app.get("/api/shuttle")
def api_shuttle():
    """작성 화면에서 '이 시간에 시작하면 끝난 뒤 어떤 셔틀을 탈 수 있나?'를 실시간으로 보여 주는 조회용 API."""
    try:
        meet = datetime.strptime(f"{request.args.get('date', '')} {request.args.get('time', '')}", FMT_DB)
        duration = int(request.args.get("duration", DEFAULT_DURATION))
        if duration not in DURATION_LABEL:
            raise ValueError
    except ValueError:
        return {"error": "date(YYYY-MM-DD), time(HH:MM), duration(분)을 확인해 주세요."}, 400
    end = meet + timedelta(minutes=duration)
    resp = {
        "end": end_label(meet, end),
        "buffer": shuttle.WALK_BUFFER_MIN,
        "routes": shuttle.check_all(meet, end),
    }
    return resp, 200, {"Cache-Control": "no-store"}


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


init_db()

if __name__ == "__main__":
    app.run(debug=True)
