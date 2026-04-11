import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify,
)
from functools import wraps
from dotenv import load_dotenv

from database.db import (
    init_db, get_connection,
    get_or_create_user, get_user_by_id, get_all_users,
    # boards
    get_boards, get_board, add_board, update_board, delete_board,
    get_or_create_default_board,
    # columns
    get_columns, add_column, update_column, delete_column,
    # tags
    get_tags, add_tag, delete_tag,
    # tasks
    get_tasks_by_column, add_task, update_task, delete_task, get_task,
    # stats
    get_stats,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "changeme")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin")


def fmt_deadline(value):
    """Convert stored ISO deadline 'YYYY-MM-DD HH:MM' → display 'DD.MM.YYYY HH:MM'."""
    if not value:
        return value
    try:
        dt = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M")
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        try:
            dt = datetime.strptime(str(value).strip(), "%Y-%m-%d")
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            return value

app.jinja_env.filters["fmt_deadline"] = fmt_deadline

PRIORITY_LABELS = {
    "low":    {"ru": "Низкий",   "en": "Low"},
    "medium": {"ru": "Средний",  "en": "Medium"},
    "high":   {"ru": "Высокий",  "en": "High"},
}

BOARD_COLORS = [
    "#5b6af0", "#e5533d", "#22c97a", "#f0a922",
    "#0099cc", "#9b59b6", "#e91e8c", "#1abc9c",
]


# ── Auth ──────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        # guard against stale session after DB wipe
        if get_user_by_id(session["user_id"]) is None:
            session.clear()
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    return get_user_by_id(session["user_id"])


@app.route("/login")
def login():
    lang = session.get("lang", "ru")
    token = request.args.get("token", "")
    error = None
    if token:
        if token.isdigit():
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE telegram_id = ?", (int(token),))
            row = cur.fetchone()
            conn.close()
            if row:
                session["user_id"] = dict(row)["id"]
                return redirect(url_for("board"))
        error = "Неверный токен. / Invalid token."
    return render_template("login.html", error=error, lang=lang)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dev-login")
def dev_login():
    if os.getenv("FLASK_DEBUG", "false").lower() != "true":
        return "Not available", 403
    init_db()
    user = get_or_create_user(telegram_id=0, username="dev_user")
    session["user_id"] = user["id"]
    return redirect(url_for("board"))


# ── Board (Kanban) ────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def board():
    user = get_current_user()
    lang = session.get("lang", "ru")

    # resolve active board
    board_id = request.args.get("board_id", type=int) or session.get("active_board_id")
    boards = get_boards(user["id"])
    if not boards:
        active_board = get_or_create_default_board(user["id"])
        boards = get_boards(user["id"])
    else:
        active_board = next((b for b in boards if b["id"] == board_id), boards[0])

    session["active_board_id"] = active_board["id"]

    columns = get_columns(active_board["id"])
    columns_data = []
    for col in columns:
        columns_data.append({
            **col,
            "tasks": get_tasks_by_column(active_board["id"], col["id"]),
        })

    tags = get_tags(user["id"])
    stats = get_stats(user["id"])

    return render_template(
        "board.html",
        user=user,
        boards=boards,
        active_board=active_board,
        columns=columns_data,
        tags=tags,
        stats=stats,
        lang=lang,
        priority_labels=PRIORITY_LABELS,
        board_colors=BOARD_COLORS,
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@app.route("/set-lang/<lang>")
def set_lang(lang):
    if lang in ("ru", "en"):
        session["lang"] = lang
    next_url = request.args.get("next") or request.referrer or url_for("board")
    return redirect(next_url)


# ── Board API ─────────────────────────────────────────────────────────────────

@app.route("/api/boards", methods=["GET"])
@login_required
def api_get_boards():
    user = get_current_user()
    return jsonify(get_boards(user["id"]))


@app.route("/api/boards", methods=["POST"])
@login_required
def api_add_board():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    color = (data.get("color") or "#5b6af0").strip()
    board = add_board(user["id"], name, color)
    return jsonify(board), 201


@app.route("/api/boards/<int:board_id>", methods=["PATCH"])
@login_required
def api_update_board(board_id):
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    ok = update_board(board_id, user["id"], **{k: v for k, v in data.items() if k in ("name", "color")})
    if ok:
        return jsonify(get_board(board_id, user["id"]))
    return jsonify({"error": "Not found"}), 404


@app.route("/api/boards/<int:board_id>", methods=["DELETE"])
@login_required
def api_delete_board(board_id):
    user = get_current_user()
    boards = get_boards(user["id"])
    if len(boards) <= 1:
        return jsonify({"error": "Cannot delete last board"}), 400
    ok = delete_board(board_id, user["id"])
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


# ── Column API ────────────────────────────────────────────────────────────────

@app.route("/api/boards/<int:board_id>/columns", methods=["GET"])
@login_required
def api_get_columns(board_id):
    user = get_current_user()
    if not get_board(board_id, user["id"]):
        return jsonify({"error": "Not found"}), 404
    return jsonify(get_columns(board_id))


@app.route("/api/boards/<int:board_id>/columns", methods=["POST"])
@login_required
def api_add_column(board_id):
    user = get_current_user()
    if not get_board(board_id, user["id"]):
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    col = add_column(board_id, name)
    return jsonify(col), 201


@app.route("/api/columns/<int:col_id>", methods=["PATCH"])
@login_required
def api_update_column(col_id):
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    # verify ownership via board
    board_id = session.get("active_board_id")
    if not board_id or not get_board(board_id, user["id"]):
        return jsonify({"error": "Forbidden"}), 403
    ok = update_column(col_id, board_id, **{k: v for k, v in data.items() if k in ("name", "position")})
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


@app.route("/api/columns/<int:col_id>", methods=["DELETE"])
@login_required
def api_delete_column(col_id):
    user = get_current_user()
    board_id = session.get("active_board_id")
    if not board_id or not get_board(board_id, user["id"]):
        return jsonify({"error": "Forbidden"}), 403
    cols = get_columns(board_id)
    if len(cols) <= 1:
        return jsonify({"error": "Cannot delete last column"}), 400
    ok = delete_column(col_id, board_id)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


# ── Task API ──────────────────────────────────────────────────────────────────

@app.route("/api/tasks", methods=["POST"])
@login_required
def api_add_task():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400

    board_id   = data.get("board_id") or session.get("active_board_id")
    column_id  = data.get("column_id")
    if not board_id or not column_id:
        return jsonify({"error": "board_id and column_id required"}), 400

    if not get_board(board_id, user["id"]):
        return jsonify({"error": "Board not found"}), 404

    task = add_task(
        user_id=user["id"],
        board_id=board_id,
        column_id=column_id,
        title=title,
        description=(data.get("description") or "").strip(),
        tag_id=data.get("tag_id") or None,
        deadline=data.get("deadline") or None,
        priority=data.get("priority", "medium"),
    )
    # attach tag info
    tags = {t["id"]: t for t in get_tags(user["id"])}
    if task.get("tag_id") and task["tag_id"] in tags:
        task["tag_name"]  = tags[task["tag_id"]]["name"]
        task["tag_color"] = tags[task["tag_id"]]["color"]
    return jsonify(task), 201


@app.route("/api/tasks/<int:task_id>", methods=["PATCH"])
@login_required
def api_update_task(task_id):
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    allowed = {"title", "description", "column_id", "priority", "deadline", "tag_id"}
    fields = {k: v for k, v in data.items() if k in allowed}
    ok = update_task(task_id, user["id"], **fields)
    if ok:
        task = get_task(task_id, user["id"])
        return jsonify(task)
    return jsonify({"error": "Not found"}), 404


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def api_delete_task(task_id):
    user = get_current_user()
    ok = delete_task(task_id, user["id"])
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


# ── Tag API ───────────────────────────────────────────────────────────────────

@app.route("/api/tags", methods=["GET"])
@login_required
def api_get_tags():
    user = get_current_user()
    return jsonify(get_tags(user["id"]))


@app.route("/api/tags", methods=["POST"])
@login_required
def api_add_tag():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "#5b6af0").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    tag = add_tag(user["id"], name, color)
    return jsonify(tag), 201


@app.route("/api/tags/<int:tag_id>", methods=["DELETE"])
@login_required
def api_delete_tag(tag_id):
    user = get_current_user()
    ok = delete_tag(tag_id, user["id"])
    if ok:
        return jsonify({"ok": True})
    return jsonify({"error": "Not found"}), 404


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    if request.args.get("token") != ADMIN_TOKEN:
        return "Forbidden", 403
    return render_template("admin.html", users=get_all_users(), admin_token=ADMIN_TOKEN)


if __name__ == "__main__":
    init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
