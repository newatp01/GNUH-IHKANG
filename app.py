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
NURSES = ["강정훈", "문병선", "이우제", "김하은", "이혜란"]
ALLOWED_EXT = {"pdf", "doc", "docx", "hwp", "hwpx"}
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
        if name in NURSES:
            session["user"] = name
            return redirect(url_for("home"))
    return render_template("select_name.html", nurses=NURSES)


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
        "home.html", projects=projects, issues=issues,
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
                    if sd <= cur <= ed:
                        entries.append({
                            "name": r["nurse_name"],
                            "half": bool(r["half_day"]),
                            "color": NURSE_COLORS[NURSES.index(r["nurse_name"]) % len(NURSE_COLORS)]
                            if r["nurse_name"] in NURSES else "gray",
                        })
                days[d] = entries
        return {"year": y, "month": m, "weeks": weeks, "days": days}

    cal1 = build_calendar(y1, m1)
    cal2 = build_calendar(y2, m2)

    summary = []
    for nurse in NURSES:
        rows = db.execute(
            "SELECT * FROM vacations WHERE nurse_name = ? ORDER BY start_date",
            (nurse,),
        ).fetchall()
        total = 0.0
        entries_text = []
        for r in rows:
            sd = date.fromisoformat(r["start_date"])
            ed = date.fromisoformat(r["end_date"])
            if r["half_day"]:
                days_count = 0.5
                label = f"{sd.month}/{sd.day}(반차)"
            else:
                days_count = (ed - sd).days + 1
                label = f"{sd.month}/{sd.day}" if sd == ed else f"{sd.month}/{sd.day}~{ed.month}/{ed.day}"
            total += days_count
            entries_text.append(label)
        summary.append({
            "name": nurse,
            "total": round(total, 1),
            "detail": ", ".join(entries_text) if entries_text else "기록 없음",
            "color": NURSE_COLORS[NURSES.index(nurse) % len(NURSE_COLORS)],
        })

    return render_template(
        "vacation.html", cal1=cal1, cal2=cal2, summary=summary,
        nurses=NURSES, today=today.isoformat(),
    )


@app.route("/vacation/add", methods=["POST"])
@login_required
def vacation_add():
    db = get_db()
    nurse_name = request.form.get("nurse_name")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date") or start_date
    half_day = 1 if request.form.get("half_day") == "on" else 0
    memo = request.form.get("memo", "").strip()
    if half_day:
        end_date = start_date
    if nurse_name in NURSES and start_date:
        db.execute(
            """INSERT INTO vacations (nurse_name, start_date, end_date, half_day, memo, created_at)
               VALUES (?,?,?,?,?,?)""",
            (nurse_name, start_date, end_date, half_day, memo, datetime.now().isoformat()),
        )
        db.commit()
    return redirect(url_for("vacation"))


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


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
        "nurse_color": lambda n: NURSE_COLORS[NURSES.index(n) % len(NURSE_COLORS)] if n in NURSES else "gray",
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
