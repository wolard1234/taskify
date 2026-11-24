import os
import sys
import json
import logging
from datetime import datetime
from html import escape
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import urlencode

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
    # sharing
    toggle_share_token, get_board_by_share_token,
    get_board_members, add_board_member, remove_board_member,
    get_boards_shared_with_user, user_can_edit_board,
    get_departments, update_department, InvalidDepartment,
    # columns
    get_columns, add_column, update_column, delete_column, reorder_columns,
    get_column_templates, save_column_template, apply_column_template,
    # tags
    get_tags, add_tag, delete_tag,
    # tasks
    get_tasks_by_column, add_task, update_task, delete_task, InvalidAssignee,
    # stats
    get_board_stats,
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "taskifyjobs_bot").lstrip("@")
WEB_URL = os.getenv("WEB_URL", "http://localhost:5000").rstrip("/")


def notify_telegram(chat_id: int, text: str, reply_markup: dict = None):
    """Send a Telegram message via Bot API (fire-and-forget)."""
    if not BOT_TOKEN or not chat_id or chat_id == 0:
        logging.warning("notify_telegram skipped: no BOT_TOKEN or chat_id=%s", chat_id)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=5)
        logging.info("notify_telegram OK: chat_id=%s status=%s", chat_id, resp.status)
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode()
            except Exception:
                pass
        logging.error("notify_telegram FAILED: chat_id=%s error=%s body=%s", chat_id, e, body)


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
    next_url = request.args.get("next", "")
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
                return redirect(next_url or url_for("board"))
        error = "Неверный токен. / Invalid token."
    return render_template("login.html", error=error, lang=lang, bot_username=BOT_USERNAME)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dev-login")
def dev_login():
    dev_login_enabled = os.getenv("TASKIFY_DEV_LOGIN", os.getenv("FLASK_DEBUG", "false"))
    if dev_login_enabled.lower() != "true":
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
    shared_boards = get_boards_shared_with_user(user["id"])
    all_boards = boards + shared_boards

    if not all_boards:
        active_board = get_or_create_default_board(user["id"])
        boards = get_boards(user["id"])
        all_boards = boards
    else:
        active_board = next((b for b in all_boards if b["id"] == board_id), all_boards[0])

    session["active_board_id"] = active_board["id"]
    is_owner = active_board["user_id"] == user["id"]

    columns = get_columns(active_board["id"])
    columns_data = []
    for col in columns:
        columns_data.append({
            **col,
            "tasks": get_tasks_by_column(active_board["id"], col["id"]),
        })

    # show board owner's tags when viewing a shared board
    tag_owner_id = active_board["user_id"] if not is_owner else user["id"]
    tags = get_tags(tag_owner_id)
    stats = get_board_stats(active_board["id"])
    members = get_board_members(active_board["id"])
    owner = user if is_owner else get_user_by_id(active_board["user_id"])
    assignees = {owner["id"]: owner["username"] or f"#{owner['id']}"}
    assignees.update({
        member["user_id"]: member["username"] or f"#{member['user_id']}"
        for member in members
    })
    departments = get_departments(active_board["user_id"], user["id"])

    return render_template(
        "board.html",
        user=user,
        boards=boards,
        shared_boards=shared_boards,
        active_board=active_board,
        is_owner=is_owner,
        columns=columns_data,
        column_templates=get_column_templates(user["id"], lang),
        tags=tags,
        stats=stats,
        members=members if is_owner else [],
        assignees=assignees,
        departments=departments,
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
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid board"}), 400
    name = data.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        return jsonify({"error": "Name required"}), 400
    color = data.get("color", "#5b6af0")
    if not isinstance(color, str):
        return jsonify({"error": "Invalid board color"}), 400
    template_id = data.get("template_id", "")
    if not isinstance(template_id, str):
        return jsonify({"error": "invalid_template"}), 400
    columns = None
    if template_id:
        template = get_column_templates(user["id"], session.get("lang", "ru")).get(template_id)
        if template is None:
            return jsonify({"error": "template_not_found"}), 404
        columns = template["columns"]
    board = add_board(user["id"], name, color.strip() or "#5b6af0", columns=columns)
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

@app.route("/api/column-templates", methods=["POST"])
@login_required
def api_save_column_template():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_template"}), 400
    name, columns = data.get("name"), data.get("columns")
    if not isinstance(name, str) or not isinstance(columns, list) or not all(isinstance(col, str) for col in columns):
        return jsonify({"error": "invalid_template"}), 400
    name = name.strip()
    columns = [col.strip() for col in columns]
    if (
        not 1 <= len(name) <= 60 or len(name.splitlines()) != 1
        or not 1 <= len(columns) <= 30
        or any(not 1 <= len(col) <= 60 or len(col.splitlines()) != 1 for col in columns)
        or len({col.casefold() for col in columns}) != len(columns)
    ):
        return jsonify({"error": "invalid_template"}), 400
    if name.casefold() == "agile":
        return jsonify({"error": "template_name_taken"}), 409
    template_id = save_column_template(session["user_id"], name, columns)
    if template_id is None:
        return jsonify({"error": "template_name_taken"}), 409
    return jsonify({"id": str(template_id), "name": name, "columns": columns}), 201


@app.route("/api/boards/<int:board_id>/column-template", methods=["PUT"])
@login_required
def api_apply_column_template(board_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("template_id"), str):
        return jsonify({"error": "invalid_template"}), 400
    user_id = session["user_id"]
    template = get_column_templates(user_id, session.get("lang", "ru")).get(data["template_id"])
    if template is None:
        return jsonify({"error": "template_not_found"}), 404
    if not apply_column_template(board_id, user_id, template["columns"]):
        return jsonify({"error": "template_forbidden"}), 403
    return jsonify({"ok": True})


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


@app.route("/api/boards/<int:board_id>/columns/order", methods=["PUT"])
@login_required
def api_reorder_columns(board_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid column order"}), 400
    previous_ids = data.get("previous_column_ids")
    column_ids = data.get("column_ids")
    for order in (previous_ids, column_ids):
        if not isinstance(order, list) or not order or any(type(item) is not int or item <= 0 for item in order):
            return jsonify({"error": "Invalid column order"}), 400
    if (
        len(previous_ids) != len(column_ids)
        or len(set(previous_ids)) != len(previous_ids)
        or set(previous_ids) != set(column_ids)
    ):
        return jsonify({"error": "Invalid column order"}), 400

    try:
        saved = reorder_columns(board_id, session["user_id"], previous_ids, column_ids)
    except PermissionError:
        return jsonify({"error": "Forbidden"}), 403
    if not saved:
        return jsonify({"error": "The board columns changed"}), 409
    return jsonify({"column_ids": column_ids})


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

def notify_task_assignee(task, actor, previous_assignee=None):
    assignee_id = task["assignee_id"]
    if assignee_id is None or assignee_id in (actor["id"], previous_assignee):
        return
    assignee = get_user_by_id(assignee_id)
    if assignee and assignee["telegram_id"]:
        actor_name = f"@{actor['username']}" if actor["username"] else f"пользователя #{actor['id']}"
        notify_telegram(
            assignee["telegram_id"],
            f"📋 <b>Вам назначена задача</b>\n{escape(task['title'])}\n\nОт {escape(actor_name)}",
            {"inline_keyboard": [[{
                "text": "Открыть задачу",
                "callback_data": f"task:view:{task['id']}",
            }]]},
        )


def task_validation_error(error):
    if session.get("lang", "ru") == "ru":
        if isinstance(error, InvalidAssignee):
            return jsonify({"error": "Выберите участника этой доски"}), 400
        if isinstance(error, InvalidDepartment):
            return jsonify({"error": "Отдел или исполнитель недоступен. Обновите страницу."}), 400
    return jsonify({"error": str(error)}), 400


@app.route("/api/tasks", methods=["POST"])
@login_required
def api_add_task():
    user = get_current_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid task"}), 400
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return jsonify({"error": "Title required"}), 400

    board_id = data.get("board_id", session.get("active_board_id"))
    department_id = data.get("department_id")
    column_id = data.get("column_id")
    if type(board_id) is not int or not 0 < board_id <= 2**63 - 1:
        return jsonify({"error": "Choose a board"}), 400
    if department_id is not None and (type(department_id) is not int or not 0 < department_id <= 2**63 - 1):
        return task_validation_error(InvalidDepartment("Department unavailable"))
    if column_id is not None and (type(column_id) is not int or not 0 < column_id <= 2**63 - 1):
        return jsonify({"error": "Choose a column on this board"}), 400

    try:
        task = add_task(
            user_id=user["id"],
            board_id=board_id,
            column_id=column_id,
            title=title.strip(),
            description=(data.get("description") or "").strip(),
            tag_ids=data.get("tag_ids") or [],
            deadline=data.get("deadline") or None,
            priority=data.get("priority", "medium"),
            assignee_id=data.get("assignee_id"),
            department_id=department_id,
        )
    except PermissionError:
        return jsonify({"error": "Forbidden"}), 403
    except ValueError as error:
        return task_validation_error(error)
    notify_task_assignee(task, user)
    task["can_open_board"] = task["board_id"] == board_id or user_can_edit_board(task["board_id"], user["id"])
    return jsonify(task), 201


@app.route("/api/tasks/<int:task_id>", methods=["PATCH"])
@login_required
def api_update_task(task_id):
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        tag_ids = (data["tag_ids"] or []) if "tag_ids" in data else None
        task, previous_assignee = update_task(task_id, user["id"], data, tag_ids=tag_ids)
    except ValueError as error:
        return task_validation_error(error)
    if not task:
        return jsonify({"error": "Not found"}), 404
    notify_task_assignee(task, user, previous_assignee)
    return jsonify(task)


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


# ── Sharing API ───────────────────────────────────────────────────────────────

@app.route("/api/boards/<int:board_id>/department", methods=["PUT"])
@login_required
def api_update_department(board_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "lead_id" not in data:
        return jsonify({"error": "Invalid department"}), 400
    lead_id, staff_ids = data["lead_id"], data.get("staff_ids")
    if (
        not isinstance(staff_ids, list)
        or any(type(id) is not int or not 0 < id <= 2**63 - 1 for id in staff_ids)
        or (lead_id is not None and (type(lead_id) is not int or not 0 < lead_id <= 2**63 - 1))
    ):
        return jsonify({"error": "Invalid department"}), 400
    try:
        saved = update_department(board_id, session["user_id"], lead_id, set(staff_ids))
    except InvalidDepartment as error:
        return jsonify({"error": "Выберите участников этой доски" if session.get("lang", "ru") == "ru" else str(error)}), 400
    if not saved:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify({"ok": True})


@app.route("/api/boards/<int:board_id>/share", methods=["POST"])
@login_required
def api_toggle_share(board_id):
    """Toggle public share link on/off. Body: { enable: true/false }"""
    user = get_current_user()
    b = get_board(board_id, user["id"])
    if not b or b["user_id"] != user["id"]:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    enable = bool(data.get("enable", True))
    token = toggle_share_token(board_id, user["id"], enable)
    share_url = f"{request.host_url}shared/{token}" if token else None
    return jsonify({"share_token": token, "share_url": share_url})


@app.route("/shared/<token>")
def shared_board(token):
    """Public read-only board view."""
    board_data = get_board_by_share_token(token)
    if not board_data:
        return "Board not found or sharing disabled.", 404
    lang = session.get("lang", "ru")
    columns = get_columns(board_data["id"])
    columns_data = []
    for col in columns:
        tasks = get_tasks_by_column(board_data["id"], col["id"])
        for task in tasks:
            task.pop("assignee_id", None)
            task.pop("assigned_by_id", None)
            task.pop("sender_name", None)
        columns_data.append({**col, "tasks": tasks})
    tags = get_tags(board_data["user_id"])
    stats = get_board_stats(board_data["id"])
    return render_template(
        "board.html",
        user=None,
        boards=[],
        shared_boards=[],
        active_board=board_data,
        is_owner=False,
        columns=columns_data,
        tags=tags,
        stats=stats,
        members=[],
        lang=lang,
        priority_labels=PRIORITY_LABELS,
        board_colors=BOARD_COLORS,
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
        readonly=True,
    )


@app.route("/api/boards/<int:board_id>/members", methods=["GET"])
@login_required
def api_get_members(board_id):
    user = get_current_user()
    b = get_board(board_id, user["id"])
    if not b or b["user_id"] != user["id"]:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(get_board_members(board_id))


@app.route("/api/boards/<int:board_id>/members", methods=["POST"])
@login_required
def api_add_member(board_id):
    """Invite user by @username. Body: { username: "@nickname" }"""
    user = get_current_user()
    b = get_board(board_id, user["id"])
    if not b or b["user_id"] != user["id"]:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    uname = (data.get("username") or "").strip()
    if not uname:
        return jsonify({"error": "username required"}), 400
    member = add_board_member(board_id, uname)
    if not member:
        err_msg = "Пользователь не найден или уже участник" if "ru" in session.get("lang", "ru") else "User not found or already a member"
        return jsonify({"error": err_msg}), 400

    # Send Telegram notification to the invited user
    next_page = f"/?board_id={board_id}"
    board_url = f"{WEB_URL}/login?" + urlencode({"token": member["telegram_id"], "next": next_page})
    inviter = user.get("username") or "User"
    board_name = b.get("name", "Board")
    msg = (
        f"📋 <b>Вас добавили в доску «{board_name}»</b>\n\n"
        f"Пригласил: @{inviter}\n"
        f"Теперь вы можете редактировать задачи на этой доске.\n\n"
        f"🔗 <a href=\"{board_url}\">Открыть доску</a>"
    )
    # Telegram rejects localhost URLs in inline keyboards,
    # so use inline button only for real HTTPS domains
    markup = None
    if "localhost" not in WEB_URL and "127.0.0.1" not in WEB_URL:
        markup = {
            "inline_keyboard": [[
                {"text": "🔗 Открыть доску", "url": board_url}
            ]]
        }
    notify_telegram(
        chat_id=member["telegram_id"],
        text=msg,
        reply_markup=markup,
    )

    return jsonify(member), 201


@app.route("/api/boards/<int:board_id>/members/<int:member_user_id>", methods=["DELETE"])
@login_required
def api_remove_member(board_id, member_user_id):
    user = get_current_user()
    b = get_board(board_id, user["id"])
    if not b or b["user_id"] != user["id"]:
        return jsonify({"error": "Forbidden"}), 403
    ok = remove_board_member(board_id, member_user_id)
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
