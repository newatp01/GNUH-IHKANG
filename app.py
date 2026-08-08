import os
import sqlite3
import calendar
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for, render_template,
    send_from_directory, abort, flash, g
)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# DATA_DIR lets you point the database/uploads at a persistent disk when
# deploying to a host like Render (set the DATA_DIR env var to the disk's
# mount path, e.g. /var/data). Defaults to this folder for local use.
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "data.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

SITE_PASSWORD = "dnfldusrn11"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "0168")  # 강정훈(관리자) 로그인 비밀번호
NURSES = ["강정훈", "김하은", "이혜란"]  # 로그인 가능한 전체 인원
VACATION_NURSES = ["김하은", "이혜란"]  # 휴가 현황에 집계되는 간호사 (강정훈은 조회만)
VACATION_MANAGERS = {"김하은", "이혜란"}  # 휴가 등록/수정/취소는 이 두 사람만
ALLOWED_EXT = {"pdf", "doc", "docx", "hwp", "hwpx"}  # 회의록
PROJECT_FILE_ALLOWED_EXT = {
    "pdf", "doc", "docx", "hwp", "hwpx", "xls", "xlsx", "ppt", "pptx",
    "png", "jpg", "jpeg", "zip", "txt", "csv",
}  # 연구 과제 첨부파일
NURSE_COLORS = ["blue", "coral", "green", "amber", "pink"]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kjh-research-site-secret-key-2026")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30MB upload limit


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT,
            status TEXT DEFAULT '진행중',
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            content TEXT NOT NULL,
            author TEXT,
            status TEXT DEFAULT 'pending',
            due_date TEXT,
            created_at TEXT,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS vacations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nurse_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            half_day INTEGER DEFAULT 0,
            memo TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS project_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT,
            uploader TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS minutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT,
            uploader TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author TEXT,
            created_at TEXT
        );
        """
    )
    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("site_auth"):
            return redirect(url_for("login"))
        if not session.get("user"):
            return redirect(url_for("select_name"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == SITE_PASSWORD:
            session["site_auth"] = True
            return redirect(url_for("select_name"))
        error = "비밀번호가 올바르지 않습니다."
    return render_template("login.html", error=error)


@app.route("/select-name", methods=["GET", "POST"])
def select_name():
    if not session.get("site_auth"):
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name")
        if name == "강정훈":
            return redirect(url_for("admin_login"))
        if name in NURSES:
            session["user"] = name
            return redirect(url_for("home"))
    return render_template("select_name.html", nurses=NURSES)


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if not session.get("site_auth"):
        return redirect(url_for("login"))
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["user"] = "강정훈"
            return redirect(url_for("home"))
        error = "관리자 비밀번호가 올바르지 않습니다."
    return render_template("admin_login.html", error=error)


@app.route("/switch-user")
def switch_user():
    session.pop("user", None)
    return redirect(url_for("select_name"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    db = get_db()
    projects = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    project_files = {}
    for p in projects:
        rows = db.execute(
            "SELECT * FROM project_files WHERE project_id = ? ORDER BY created_at DESC",
            (p["id"],),
        ).fetchall()
        project_files[p["id"]] = rows
    issues = db.execute(
        """SELECT issues.*, projects.name AS project_name, projects.code AS project_code
           FROM issues LEFT JOIN projects ON issues.project_id = projects.id
           WHERE issues.status != 'resolved'
           ORDER BY (issues.due_date IS NULL), issues.due_date ASC, issues.created_at DESC"""
    ).fetchall()
    archive_count = db.execute(
        "SELECT COUNT(*) c FROM issues WHERE status = 'resolved'"
    ).fetchone()["c"]
    today = date.today().isoformat()
    return render_template(
        "home.html", projects=projects, issues=issues, project_files=project_files,
        archive_count=archive_count, today=today
    )


@app.route("/project/add", methods=["POST"])
@login_required
def project_add():
    db = get_db()
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()
    if name:
        db.execute(
            "INSERT INTO projects (name, code, status, created_at) VALUES (?,?,?,?)",
            (name, code, "진행중", datetime.now().isoformat()),
        )
        db.commit()
    return redirect(url_for("home"))


@app.route("/project/<int:project_id>/delete", methods=["POST"])
@login_required
def project_delete(project_id):
    db = get_db()
    # 과제를 지워도 거기 달려있던 이슈 자체는 남기고, 과제 태그만 떼어냅니다.
    db.execute("UPDATE issues SET project_id = NULL WHERE project_id = ?", (project_id,))
    files = db.execute("SELECT * FROM project_files WHERE project_id = ?", (project_id,)).fetchall()
    for pf in files:
        try:
            os.remove(os.path.join(UPLOAD_DIR, pf["filename"]))
        except OSError:
            pass
    db.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    return redirect(url_for("home"))


@app.route("/project/<int:project_id>/files/upload", methods=["POST"])
@login_required
def project_files_upload(project_id):
    db = get_db()
    project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        abort(404)
    files = request.files.getlist("files")
    saved = 0
    for file in files:
        if not file or file.filename == "":
            continue
        if not allowed_file(file.filename, PROJECT_FILE_ALLOWED_EXT):
            continue
        original = file.filename
        safe = secure_filename(original)
        stored = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe}"
        file.save(os.path.join(UPLOAD_DIR, stored))
        db.execute(
            """INSERT INTO project_files (project_id, filename, original_filename, uploader, created_at)
               VALUES (?,?,?,?,?)""",
            (project_id, stored, original, session.get("user"), datetime.now().isoformat()),
        )
        saved += 1
    db.commit()
    if saved == 0:
        flash("업로드할 수 있는 파일이 없습니다. 허용된 형식인지 확인해주세요.")
    return redirect(url_for("home"))


@app.route("/project/files/<int:file_id>/download")
@login_required
def project_file_download(file_id):
    db = get_db()
    row = db.execute("SELECT * FROM project_files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR, row["filename"], as_attachment=True,
        download_name=row["original_filename"],
    )


@app.route("/project/files/<int:file_id>/delete", methods=["POST"])
@login_required
def project_file_delete(file_id):
    db = get_db()
    row = db.execute("SELECT * FROM project_files WHERE id = ?", (file_id,)).fetchone()
    if row:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["filename"]))
        except OSError:
            pass
        db.execute("DELETE FROM project_files WHERE id = ?", (file_id,))
        db.commit()
    return redirect(url_for("home"))


@app.route("/issue/add", methods=["POST"])
@login_required
def issue_add():
    db = get_db()
    content = request.form.get("content", "").strip()
    project_id = request.form.get("project_id") or None
    due_date = request.form.get("due_date") or None
    if content:
        db.execute(
            """INSERT INTO issues (project_id, content, author, status, due_date, created_at)
               VALUES (?,?,?,?,?,?)""",
            (project_id, content, session.get("user"), "pending", due_date,
             datetime.now().isoformat()),
        )
        db.commit()
    return redirect(url_for("home"))


@app.route("/issue/<int:issue_id>/status", methods=["POST"])
@login_required
def issue_status(issue_id):
    db = get_db()
    new_status = request.form.get("status")
    if new_status not in ("pending", "in_progress", "resolved"):
        abort(400)
    resolved_at = datetime.now().isoformat() if new_status == "resolved" else None
    db.execute(
        "UPDATE issues SET status = ?, resolved_at = ? WHERE id = ?",
        (new_status, resolved_at, issue_id),
    )
    db.commit()
    back = request.form.get("back") or url_for("home")
    return redirect(back)


@app.route("/issue/<int:issue_id>/delete", methods=["POST"])
@login_required
def issue_delete(issue_id):
    db = get_db()
    back = request.form.get("back") or url_for("home")
    db.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
    db.commit()
    return redirect(back)


@app.route("/issues/archive")
@login_required
def issue_archive():
    db = get_db()
    issues = db.execute(
        """SELECT issues.*, projects.name AS project_name, projects.code AS project_code
           FROM issues LEFT JOIN projects ON issues.project_id = projects.id
           WHERE issues.status = 'resolved'
           ORDER BY issues.resolved_at DESC"""
    ).fetchall()
    return render_template("issue_archive.html", issues=issues)


def month_matrix(year, month):
    cal = calendar.Calendar(firstweekday=6)
    return cal.monthdayscalendar(year, month)


def add_month(year, month, n=1):
    m = month - 1 + n
    y = year + m // 12
    m = m % 12 + 1
    return y, m


@app.route("/vacation", methods=["GET"])
@login_required
def vacation():
    db = get_db()
    today = date.today()
    y1, m1 = today.year, today.month
    y2, m2 = add_month(y1, m1, 1)

    def build_calendar(y, m):
        weeks = month_matrix(y, m)
        rows = db.execute(
            "SELECT * FROM vacations WHERE start_date <= ? AND end_date >= ?",
            (date(y, m, calendar.monthrange(y, m)[1]).isoformat(), date(y, m, 1).isoformat()),
        ).fetchall()
        days = {}
        for w in weeks:
            for d in w:
                if d == 0:
                    continue
                cur = date(y, m, d)
                entries = []
                for r in rows:
                    sd = date.fromisoformat(r["start_date"])
                    ed = date.fromisoformat(r["end_date"])
                    if ed < sd:  # 예전에 잘못 저장된(종료일<시작일) 기록도 화면에서는 항상 바로잡아 보여준다
                        sd, ed = ed, sd
                    if sd <= cur <= ed:
                        entries.append({
                            "name": r["nurse_name"],
                            "half": bool(r["half_day"]),
                            "color": NURSE_COLORS[VACATION_NURSES.index(r["nurse_name"]) % len(NURSE_COLORS)]
                            if r["nurse_name"] in VACATION_NURSES else "gray",
                        })
                days[d] = entries
        return {"year": y, "month": m, "weeks": weeks, "days": days}

    cal1 = build_calendar(y1, m1)
    cal2 = build_calendar(y2, m2)

    summary = []
    for nurse in VACATION_NURSES:
        rows = db.execute(
            "SELECT * FROM vacations WHERE nurse_name = ? ORDER BY start_date",
            (nurse,),
        ).fetchall()
        total = 0.0
        entries = []
        for r in rows:
            sd = date.fromisoformat(r["start_date"])
            ed = date.fromisoformat(r["end_date"])
            if ed < sd:  # 예전에 잘못 저장된(종료일<시작일) 기록도 화면에서는 항상 바로잡아 보여준다
                sd, ed = ed, sd
            if r["half_day"]:
                days_count = 0.5
                label = f"{sd.month}/{sd.day}(반차)"
            else:
                days_count = (ed - sd).days + 1
                label = f"{sd.month}/{sd.day}" if sd == ed else f"{sd.month}/{sd.day}~{ed.month}/{ed.day}"
            total += days_count
            entries.append({"id": r["id"], "label": label})
        summary.append({
            "name": nurse,
            "total": round(total, 1),
            "entries": entries,
            "color": NURSE_COLORS[VACATION_NURSES.index(nurse) % len(NURSE_COLORS)],
        })

    return render_template(
        "vacation.html", cal1=cal1, cal2=cal2, summary=summary,
        nurses=VACATION_NURSES, today=today.isoformat(),
        can_manage_vacation=session.get("user") in VACATION_MANAGERS,
    )


def _normalize_range(start_date, end_date, half_day):
    """시작일/종료일을 date 객체로 바꾸고, 종료일이 시작일보다 빠르면
    자동으로 순서를 바꿔서 항상 올바른(음수가 나오지 않는) 구간으로 만든다."""
    sd = date.fromisoformat(start_date)
    ed = date.fromisoformat(end_date) if end_date else sd
    if half_day:
        ed = sd
    if ed < sd:
        sd, ed = ed, sd
    return sd, ed


@app.route("/vacation/add", methods=["POST"])
@login_required
def vacation_add():
    if session.get("user") not in VACATION_MANAGERS:
        abort(403)
    db = get_db()
    nurse_name = request.form.get("nurse_name")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date") or start_date
    half_day = 1 if request.form.get("half_day") == "on" else 0
    memo = request.form.get("memo", "").strip()
    if nurse_name in VACATION_NURSES and start_date:
        sd, ed = _normalize_range(start_date, end_date, half_day)
        db.execute(
            """INSERT INTO vacations (nurse_name, start_date, end_date, half_day, memo, created_at)
               VALUES (?,?,?,?,?,?)""",
            (nurse_name, sd.isoformat(), ed.isoformat(), half_day, memo, datetime.now().isoformat()),
        )
        db.commit()
    return redirect(url_for("vacation"))


@app.route("/vacation/<int:vac_id>/edit", methods=["GET", "POST"])
@login_required
def vacation_edit(vac_id):
    if session.get("user") not in VACATION_MANAGERS:
        abort(403)
    db = get_db()
    row = db.execute("SELECT * FROM vacations WHERE id = ?", (vac_id,)).fetchone()
    if not row:
        abort(404)

    if request.method == "POST":
        if request.form.get("action") == "delete":
            db.execute("DELETE FROM vacations WHERE id = ?", (vac_id,))
            db.commit()
            return redirect(url_for("vacation"))

        nurse_name = request.form.get("nurse_name")
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date") or start_date
        half_day = 1 if request.form.get("half_day") == "on" else 0
        memo = request.form.get("memo", "").strip()
        if nurse_name in VACATION_NURSES and start_date:
            sd, ed = _normalize_range(start_date, end_date, half_day)
            db.execute(
                """UPDATE vacations SET nurse_name=?, start_date=?, end_date=?, half_day=?, memo=?
                   WHERE id=?""",
                (nurse_name, sd.isoformat(), ed.isoformat(), half_day, memo, vac_id),
            )
            db.commit()
        return redirect(url_for("vacation"))

    return render_template("vacation_edit.html", v=row, nurses=VACATION_NURSES)


@app.route("/vacation/reset-all", methods=["POST"])
@login_required
def vacation_reset_all():
    if session.get("user") != "강정훈":
        abort(403)
    db = get_db()
    db.execute("DELETE FROM vacations")
    db.commit()
    flash("모든 간호사의 휴가 기록이 초기화되었습니다.")
    return redirect(url_for("vacation"))


def allowed_file(filename, ext_set=None):
    ext_set = ext_set or ALLOWED_EXT
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ext_set


@app.route("/minutes")
@login_required
def minutes():
    db = get_db()
    rows = db.execute("SELECT * FROM minutes ORDER BY created_at DESC").fetchall()
    return render_template("minutes.html", minutes=rows)


@app.route("/minutes/upload", methods=["POST"])
@login_required
def minutes_upload():
    db = get_db()
    title = request.form.get("title", "").strip()
    file = request.files.get("file")
    if not title or not file or file.filename == "":
        flash("제목과 파일을 모두 입력해주세요.")
        return redirect(url_for("minutes"))
    if not allowed_file(file.filename):
        flash("PDF, 워드(doc/docx), 한글(hwp/hwpx) 파일만 업로드할 수 있습니다.")
        return redirect(url_for("minutes"))
    original = file.filename
    safe = secure_filename(original)
    stored = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe}"
    file.save(os.path.join(UPLOAD_DIR, stored))
    db.execute(
        """INSERT INTO minutes (title, filename, original_filename, uploader, created_at)
           VALUES (?,?,?,?,?)""",
        (title, stored, original, session.get("user"), datetime.now().isoformat()),
    )
    db.commit()
    return redirect(url_for("minutes"))


@app.route("/minutes/download/<int:minute_id>")
@login_required
def minutes_download(minute_id):
    db = get_db()
    row = db.execute("SELECT * FROM minutes WHERE id = ?", (minute_id,)).fetchone()
    if not row:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR, row["filename"], as_attachment=True,
        download_name=row["original_filename"],
    )


@app.route("/minutes/<int:minute_id>/delete", methods=["POST"])
@login_required
def minutes_delete(minute_id):
    db = get_db()
    row = db.execute("SELECT * FROM minutes WHERE id = ?", (minute_id,)).fetchone()
    if row:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["filename"]))
        except OSError:
            pass
        db.execute("DELETE FROM minutes WHERE id = ?", (minute_id,))
        db.commit()
    return redirect(url_for("minutes"))


@app.route("/board")
@login_required
def board():
    db = get_db()
    posts = db.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    return render_template("board.html", posts=posts)


@app.route("/board/add", methods=["POST"])
@login_required
def board_add():
    db = get_db()
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    if title and content:
        db.execute(
            "INSERT INTO posts (title, content, author, created_at) VALUES (?,?,?,?)",
            (title, content, session.get("user"), datetime.now().isoformat()),
        )
        db.commit()
    return redirect(url_for("board"))


@app.route("/board/<int:post_id>")
@login_required
def board_detail(post_id):
    db = get_db()
    post = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        abort(404)
    return render_template("post_detail.html", post=post)


@app.context_processor
def inject_globals():
    return {
        "current_user": session.get("user"),
        "nurse_color": lambda n: NURSE_COLORS[VACATION_NURSES.index(n) % len(NURSE_COLORS)] if n in VACATION_NURSES else "gray",
        "can_manage_vacation": session.get("user") in VACATION_MANAGERS,
        "is_admin": session.get("user") == "강정훈",
    }


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5050))
    print("=" * 50)
    print("강정훈 연구 사이트가 시작되었습니다.")
    print(f"브라우저에서 http://127.0.0.1:{port} 으로 접속하세요.")
    print(f"같은 네트워크의 다른 사람은 http://<이 PC의 IP>:{port} 으로 접속할 수 있습니다.")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
else:
    init_db()
