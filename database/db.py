import sqlite3
import os
import uuid
import json
from contextlib import closing
from datetime import datetime

DB_PATH = os.getenv("TASKIFY_DB_PATH") or os.path.join(os.path.dirname(__file__), "taskify.db")

DEFAULT_COLUMNS = [
    {"key": "todo", "name_ru": "К выполнению", "name_en": "To Do"},
    {"key": "in_progress", "name_ru": "В процессе", "name_en": "In Progress"},
    {"key": "done", "name_ru": "Готово", "name_en": "Done"},
]
AGILE_COLUMNS = [
    {"key": "todo", "name_ru": "Бэклог", "name_en": "Backlog"},
    {"key": "in_progress", "name_ru": "В работе", "name_en": "In Progress"},
    {"key": "review", "name_ru": "На проверке", "name_en": "In Review"},
    DEFAULT_COLUMNS[-1],
]
STATUS_KEYS = {
    col[f"name_{lang}"].casefold(): col["key"]
    for col in DEFAULT_COLUMNS + AGILE_COLUMNS for lang in ("ru", "en")
}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username    TEXT,
            full_name   TEXT NOT NULL DEFAULT '',
            department_id INTEGER REFERENCES boards(id) ON DELETE SET NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS boards (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL DEFAULT 'My Board',
            color       TEXT NOT NULL DEFAULT '#5b6af0',
            position    INTEGER NOT NULL DEFAULT 0,
            share_token TEXT DEFAULT NULL,
            department_lead_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS board_members (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id   INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role       TEXT NOT NULL DEFAULT 'editor',
            department_staff INTEGER NOT NULL DEFAULT 0,
            added_at   TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(board_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS columns (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id   INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            key        TEXT NOT NULL,
            name       TEXT NOT NULL,
            position   INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS column_templates (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name         TEXT NOT NULL COLLATE NOCASE,
            columns_json TEXT NOT NULL,
            UNIQUE(user_id, name)
        );

        CREATE TABLE IF NOT EXISTS tags (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name    TEXT NOT NULL,
            color   TEXT NOT NULL DEFAULT '#5b6af0'
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            assignee_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            assigned_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            board_id    INTEGER REFERENCES boards(id) ON DELETE CASCADE,
            column_id   INTEGER REFERENCES columns(id) ON DELETE SET NULL,
            tag_id      INTEGER REFERENCES tags(id) ON DELETE SET NULL,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            priority    TEXT NOT NULL DEFAULT 'medium',
            deadline    TEXT,
            position    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS task_tags (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (task_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS telegram_chats (
            chat_id INTEGER PRIMARY KEY,
            last_message_id INTEGER NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    _migrate()


def _migrate():
    """Non-destructive migration: add missing columns/tables if upgrading old DB."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    # check if boards table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='boards'")
    if not cur.fetchone():
        conn.close()
        return  # fresh DB, nothing to migrate
    user_cols = {row["name"] for row in cur.execute("PRAGMA table_info(users)")}
    if "full_name" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN full_name TEXT NOT NULL DEFAULT ''")
    if "department_id" not in user_cols:
        cur.execute("ALTER TABLE users ADD COLUMN department_id INTEGER REFERENCES boards(id) ON DELETE SET NULL")
    # check if tasks has board_id
    cur.execute("PRAGMA table_info(tasks)")
    cols = {row["name"] for row in cur.fetchall()}
    if "board_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE")
    if "column_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN column_id INTEGER REFERENCES columns(id) ON DELETE SET NULL")
    if "tag_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN tag_id INTEGER REFERENCES tags(id) ON DELETE SET NULL")
    if "assignee_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN assignee_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    if "assigned_by_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN assigned_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    # ensure task_tags junction table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_tags'")
    if not cur.fetchone():
        cur.execute("""CREATE TABLE IF NOT EXISTS task_tags (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (task_id, tag_id)
        )""")
        # migrate old tag_id data into junction table
        cur.execute("SELECT id, tag_id FROM tasks WHERE tag_id IS NOT NULL")
        for row in cur.fetchall():
            cur.execute(
                "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
                (row["id"], row["tag_id"]),
            )
    # boards: add share_token column if missing
    cur.execute("PRAGMA table_info(boards)")
    board_cols = {row["name"] for row in cur.fetchall()}
    if "share_token" not in board_cols:
        cur.execute("ALTER TABLE boards ADD COLUMN share_token TEXT DEFAULT NULL")
    if "department_lead_id" not in board_cols:
        cur.execute("ALTER TABLE boards ADD COLUMN department_lead_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    # board_members table
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='board_members'")
    if not cur.fetchone():
        cur.execute("""CREATE TABLE IF NOT EXISTS board_members (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role     TEXT NOT NULL DEFAULT 'editor',
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
             UNIQUE(board_id, user_id)
        )""")
    if not any(row["name"] == "department_staff" for row in cur.execute("PRAGMA table_info(board_members)")):
        cur.execute("ALTER TABLE board_members ADD COLUMN department_staff INTEGER NOT NULL DEFAULT 0")
    # remove old status column if present — NOT removing (safe fallback)
    conn.commit()
    conn.close()


def record_telegram_message(chat_id: int, message_id: int):
    with closing(get_connection()) as conn, conn:
        conn.execute(
            """INSERT INTO telegram_chats (chat_id, last_message_id) VALUES (?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET last_message_id = excluded.last_message_id
               WHERE excluded.last_message_id > telegram_chats.last_message_id""",
            (chat_id, message_id),
        )


def is_latest_telegram_message(chat_id: int, message_id: int) -> bool:
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT 1 FROM telegram_chats WHERE chat_id = ? AND last_message_id = ?",
            (chat_id, message_id),
        ).fetchone() is not None


# ── Users ─────────────────────────────────────────────────────────────────────

def get_or_create_user(telegram_id: int, username: str = "") -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username),
        )
        conn.commit()
        cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cur.fetchone()
    conn.close()
    return dict(row)


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def register_user(user_id: int, department_id: int, full_name: str) -> bool:
    with closing(get_connection()) as conn, conn:
        result = conn.execute(
            """UPDATE users SET department_id = ?, full_name = ?
               WHERE id = ? AND (full_name = '' OR department_id IS NULL)
                 AND EXISTS (SELECT 1 FROM boards WHERE id = ? AND department_lead_id IS NOT NULL)""",
            (department_id, full_name, user_id, department_id),
        )
        return result.rowcount == 1


# ── Boards ────────────────────────────────────────────────────────────────────

def get_boards(user_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM boards WHERE user_id = ? ORDER BY position ASC, id ASC",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_board(board_id: int, user_id: int) -> dict | None:
    """Get board if user is owner OR member."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM boards WHERE id = ?", (board_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    board = dict(row)
    if board["user_id"] == user_id:
        conn.close()
        return board
    # check membership
    cur.execute(
        "SELECT id FROM board_members WHERE board_id = ? AND user_id = ?",
        (board_id, user_id),
    )
    if cur.fetchone():
        conn.close()
        return board
    conn.close()
    return None


def add_board(user_id: int, name: str, color: str = "#5b6af0", *, columns: list[str] | None = None) -> dict:
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM boards WHERE user_id = ?", (user_id,)).fetchone()[0]
        board_id = conn.execute(
            "INSERT INTO boards (user_id, name, color, position) VALUES (?, ?, ?, ?)",
            (user_id, name, color, pos),
        ).lastrowid
        _apply_column_names(conn, board_id, columns if columns is not None else [col["name_ru"] for col in DEFAULT_COLUMNS])
        return dict(conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone())


def update_board(board_id: int, user_id: int, **fields) -> bool:
    allowed = {"name", "color", "position"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [board_id, user_id]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE boards SET {set_clause} WHERE id = ? AND user_id = ?", values)
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_board(board_id: int, user_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM boards WHERE id = ? AND user_id = ?", (board_id, user_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def get_or_create_default_board(user_id: int) -> dict:
    boards = get_boards(user_id)
    if boards:
        return boards[0]
    return add_board(user_id, "Мои задачи")


# ── Board Sharing ─────────────────────────────────────────────────────────────

def toggle_share_token(board_id: int, user_id: int, enable: bool) -> str | None:
    """Enable or disable public share link. Returns share_token or None."""
    conn = get_connection()
    cur = conn.cursor()
    if enable:
        token = uuid.uuid4().hex[:12]
        cur.execute(
            "UPDATE boards SET share_token = ? WHERE id = ? AND user_id = ?",
            (token, board_id, user_id),
        )
    else:
        token = None
        cur.execute(
            "UPDATE boards SET share_token = NULL WHERE id = ? AND user_id = ?",
            (board_id, user_id),
        )
    conn.commit()
    conn.close()
    return token


def get_board_by_share_token(token: str) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM boards WHERE share_token = ?", (token,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Board Members ─────────────────────────────────────────────────────────────

def get_board_members(board_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT bm.*, u.username, u.telegram_id
           FROM board_members bm
           JOIN users u ON bm.user_id = u.id
           WHERE bm.board_id = ?
           ORDER BY bm.added_at ASC""",
        (board_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_board_member(board_id: int, username: str) -> dict | None:
    """Invite a user by @username. Returns member dict or None if user not found."""
    conn = get_connection()
    cur = conn.cursor()
    # strip leading @ if present
    clean = username.lstrip("@").strip()
    if not clean:
        conn.close()
        return None
    cur.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (clean,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    target_user_id = row["id"]
    # check not already owner
    cur.execute("SELECT user_id FROM boards WHERE id = ?", (board_id,))
    board_row = cur.fetchone()
    if board_row and board_row["user_id"] == target_user_id:
        conn.close()
        return None  # can't add owner as member
    try:
        cur.execute(
            "INSERT INTO board_members (board_id, user_id) VALUES (?, ?)",
            (board_id, target_user_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return None  # already a member
    member_id = cur.lastrowid
    cur.execute(
        """SELECT bm.*, u.username, u.telegram_id
           FROM board_members bm
           JOIN users u ON bm.user_id = u.id
           WHERE bm.id = ?""",
        (member_id,),
    )
    mrow = cur.fetchone()
    conn.close()
    return dict(mrow) if mrow else None


def remove_board_member(board_id: int, member_user_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM board_members WHERE board_id = ? AND user_id = ?",
        (board_id, member_user_id),
    )
    changed = cur.rowcount > 0
    if changed:
        cur.execute("UPDATE boards SET department_lead_id = NULL WHERE id = ? AND department_lead_id = ?",
                    (board_id, member_user_id))
        cur.execute(
            "UPDATE tasks SET assignee_id = NULL WHERE board_id = ? AND assignee_id = ?",
            (board_id, member_user_id),
        )
    conn.commit()
    conn.close()
    return changed


def get_boards_shared_with_user(user_id: int) -> list[dict]:
    """Get boards where user is a member (not owner)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT b.*, bm.role, u.username as owner_name
           FROM board_members bm
           JOIN boards b ON bm.board_id = b.id
           JOIN users u ON b.user_id = u.id
           WHERE bm.user_id = ?
           ORDER BY b.name ASC""",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def user_can_edit_board(board_id: int, user_id: int) -> bool:
    """Check if user is owner or member of a board."""
    with closing(get_connection()) as conn:
        return _board_has_editor(conn, board_id, user_id)


def _board_has_editor(conn, board_id, user_id):
    return conn.execute(
        """SELECT 1 FROM boards WHERE id = ? AND (
               user_id = ? OR EXISTS (
                   SELECT 1 FROM board_members WHERE board_id = boards.id AND user_id = ?
               )
           )""",
        (board_id, user_id, user_id),
    ).fetchone() is not None


BOARD_RECIPIENTS = """
    SELECT id AS board_id, user_id, 0 AS manual_staff, 0 AS registered_staff FROM boards
    UNION ALL SELECT board_id, user_id, department_staff, 0 FROM board_members
    UNION ALL SELECT department_id, id, 0, 1 FROM users WHERE department_id IS NOT NULL AND full_name <> ''
"""


def _assignee_label(row):
    return f"@{row['username']}" if row["username"] else row["full_name"] or f"#{row['user_id']}"


def get_board_assignees(board_id: int) -> dict[int, str]:
    with closing(get_connection()) as conn:
        return {row["user_id"]: _assignee_label(row) for row in conn.execute(
            f"""SELECT DISTINCT r.user_id, u.username, u.full_name
                FROM ({BOARD_RECIPIENTS}) r JOIN users u ON u.id = r.user_id
                WHERE r.board_id = ?""", (board_id,),
        )}


def get_departments(owner_id: int, viewer_id: int) -> dict:
    with closing(get_connection()) as conn:
        return _departments(conn, owner_id, viewer_id)


def get_registration_departments() -> list[dict]:
    with closing(get_connection()) as conn:
        return [dict(row) for row in conn.execute(
            """SELECT id, name, department_lead_id FROM boards WHERE department_lead_id IS NOT NULL
               ORDER BY name COLLATE NOCASE, id"""
        )]


def _departments(conn, owner_id, viewer_id):
    departments = {}
    team_member = viewer_id == owner_id
    for row in conn.execute(
        f"""SELECT b.id AS board_id, b.name, b.department_lead_id AS lead_id,
                   r.user_id, u.username, u.full_name,
                   (r.user_id = b.department_lead_id OR r.manual_staff) AS configured_staff
            FROM boards b JOIN ({BOARD_RECIPIENTS}) r ON r.board_id = b.id
            JOIN users u ON u.id = r.user_id
            WHERE b.user_id = ? AND b.department_lead_id IS NOT NULL
              AND (r.user_id = b.department_lead_id OR r.manual_staff OR r.registered_staff)
            ORDER BY b.position, b.id, u.username, u.id""", (owner_id,),
    ):
        department = departments.setdefault(row["board_id"], {"name": row["name"], "lead_id": row["lead_id"], "staff": {}})
        department["staff"][row["user_id"]] = _assignee_label(row)
        team_member = team_member or (row["user_id"] == viewer_id and row["configured_staff"])
    return departments if team_member else {}


def update_department(board_id: int, owner_id: int, lead_id: int | None, staff_ids: set[int]) -> bool:
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM boards WHERE id = ? AND user_id = ?", (board_id, owner_id)).fetchone():
            return False
        members = {row["user_id"] for row in conn.execute("SELECT user_id FROM board_members WHERE board_id = ?", (board_id,))}
        if not staff_ids <= members or (lead_id is not None and lead_id != owner_id and lead_id not in members):
            raise InvalidDepartment("Choose users who are members of the board")
        conn.execute("UPDATE boards SET department_lead_id = ? WHERE id = ?", (lead_id, board_id))
        conn.executemany("UPDATE board_members SET department_staff = ? WHERE board_id = ? AND user_id = ?",
                         ((int(user_id in staff_ids), board_id, user_id) for user_id in members))
        return True


# ── Columns ───────────────────────────────────────────────────────────────────

def get_column_templates(user_id: int, lang: str) -> dict:
    label = "name_en" if lang == "en" else "name_ru"
    templates = {"agile": {"name": "Agile", "columns": [col[label] for col in AGILE_COLUMNS]}}
    with closing(get_connection()) as conn:
        for row in conn.execute("SELECT id, name, columns_json FROM column_templates WHERE user_id = ? ORDER BY id", (user_id,)):
            templates[str(row["id"])] = {"name": row["name"], "columns": json.loads(row["columns_json"])}
    return templates


def save_column_template(user_id: int, name: str, names: list[str]) -> int | None:
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if any(row["name"].casefold() == name.casefold() for row in conn.execute(
            "SELECT name FROM column_templates WHERE user_id = ?", (user_id,)
        )):
            return None
        return conn.execute(
            "INSERT INTO column_templates (user_id, name, columns_json) VALUES (?, ?, ?)",
            (user_id, name, json.dumps(names, ensure_ascii=False)),
        ).lastrowid


def apply_column_template(board_id: int, user_id: int, names: list[str]) -> bool:
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM boards WHERE id = ? AND user_id = ?", (board_id, user_id)).fetchone():
            return False
        _apply_column_names(conn, board_id, names)
        return True


def _apply_column_names(conn, board_id: int, names: list[str]):
    remaining = {row["id"]: row for row in conn.execute(
        """SELECT c.id, c.name, c.key, EXISTS(SELECT 1 FROM tasks t WHERE t.column_id = c.id) AS has_tasks
           FROM columns c WHERE c.board_id = ? ORDER BY c.position, c.id""", (board_id,)
    )}
    matches = {}
    # Match names before status keys so a rename cannot take a later exact match.
    for name in names:
        match = next((col for col in remaining.values() if col["name"].casefold() == name.casefold()), None)
        if match:
            matches[name] = remaining.pop(match["id"])

    statuses = {name: STATUS_KEYS.get(name.casefold()) for name in names}
    for name, key in statuses.items():
        if name in matches or key is None:
            continue
        match = next((col for col in remaining.values() if col["key"] == key), None)
        if match:
            matches[name] = remaining.pop(match["id"])

    kept = [col for col in remaining.values() if col["has_tasks"]]
    reserved = {col["key"] for col in [*matches.values(), *kept]}
    for position, (name, key) in enumerate(statuses.items()):
        col = matches.get(name)
        if key is None or key in reserved or (col and not col["key"].startswith("col_")):
            key = col["key"] if col else f"col_{uuid.uuid4().hex}"
        reserved.add(key)
        if col:
            conn.execute("UPDATE columns SET name = ?, key = ?, position = ? WHERE id = ?", (name, key, position, col["id"]))
        else:
            conn.execute(
                "INSERT INTO columns (board_id, key, name, position) VALUES (?, ?, ?, ?)", (board_id, key, name, position)
            )

    conn.executemany("UPDATE columns SET position = ? WHERE id = ?",
                     ((position, col["id"]) for position, col in enumerate(kept, start=len(names))))
    conn.executemany("DELETE FROM columns WHERE id = ?", ((col["id"],) for col in remaining.values() if not col["has_tasks"]))


def get_columns(board_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM columns WHERE board_id = ? ORDER BY position ASC, id ASC",
        (board_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reorder_columns(board_id: int, user_id: int, previous_ids: list[int], column_ids: list[int]) -> bool:
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not _board_has_editor(conn, board_id, user_id):
            raise PermissionError("Board access required")
        current_ids = [
            row["id"] for row in conn.execute(
                "SELECT id FROM columns WHERE board_id = ? ORDER BY position, id", (board_id,)
            )
        ]
        if current_ids == column_ids:
            return True
        if current_ids != previous_ids:
            return False
        conn.executemany(
            "UPDATE columns SET position = ? WHERE id = ? AND board_id = ?",
            ((position, column_id, board_id) for position, column_id in enumerate(column_ids)),
        )
        return True


def add_column(board_id: int, name: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    cur.execute("SELECT COALESCE(MAX(position),0)+1 FROM columns WHERE board_id = ?", (board_id,))
    pos = cur.fetchone()[0]
    key = f"col_{int(datetime.now().timestamp())}"
    cur.execute(
        "INSERT INTO columns (board_id, key, name, position) VALUES (?, ?, ?, ?)",
        (board_id, key, name, pos),
    )
    conn.commit()
    col_id = cur.lastrowid
    cur.execute("SELECT * FROM columns WHERE id = ?", (col_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row)


def update_column(col_id: int, board_id: int, **fields) -> bool:
    allowed = {"name", "position"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [col_id, board_id]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE columns SET {set_clause} WHERE id = ? AND board_id = ?", values)
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def delete_column(col_id: int, board_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM columns WHERE id = ? AND board_id = ?", (col_id, board_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


# ── Tags ──────────────────────────────────────────────────────────────────────

def get_tags(user_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tags WHERE user_id = ? ORDER BY name", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_tag(user_id: int, name: str, color: str = "#5b6af0") -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tags (user_id, name, color) VALUES (?, ?, ?)",
        (user_id, name, color),
    )
    conn.commit()
    tag_id = cur.lastrowid
    cur.execute("SELECT * FROM tags WHERE id = ?", (tag_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row)


def delete_tag(tag_id: int, user_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tags WHERE id = ? AND user_id = ?", (tag_id, user_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


# ── Task-Tags (many-to-many) ──────────────────────────────────────────────────

def set_task_tags(task_id: int, tag_ids: list[int]):
    """Replace all tags on a task with given tag_ids list."""
    with closing(get_connection()) as conn, conn:
        _set_task_tags(conn, task_id, tag_ids)


def _set_task_tags(conn, task_id, tag_ids):
    cur = conn.cursor()
    cur.execute("DELETE FROM task_tags WHERE task_id = ?", (task_id,))
    for tid in tag_ids:
        cur.execute(
            "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
            (task_id, tid),
        )


def get_task_tags(task_id: int) -> list[dict]:
    """Return list of tags for a task."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT tg.id, tg.name, tg.color
           FROM task_tags tt JOIN tags tg ON tt.tag_id = tg.id
           WHERE tt.task_id = ?
           ORDER BY tg.name""",
        (task_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _attach_tags_to_tasks(tasks: list[dict]) -> list[dict]:
    """Given a list of task dicts, attach 'tags' list to each."""
    if not tasks:
        return tasks
    conn = get_connection()
    cur = conn.cursor()
    task_ids = [t["id"] for t in tasks]
    placeholders = ",".join("?" * len(task_ids))
    cur.execute(
        f"""SELECT tt.task_id, tg.id, tg.name, tg.color
            FROM task_tags tt JOIN tags tg ON tt.tag_id = tg.id
            WHERE tt.task_id IN ({placeholders})
            ORDER BY tg.name""",
        task_ids,
    )
    tag_map: dict[int, list[dict]] = {}
    for row in cur.fetchall():
        tag_map.setdefault(row["task_id"], []).append(
            {"id": row["id"], "name": row["name"], "color": row["color"]}
        )
    conn.close()
    for t in tasks:
        t["tags"] = tag_map.get(t["id"], [])
    return tasks


# ── Tasks ─────────────────────────────────────────────────────────────────────

TASKS_WITH_SENDER = """
    SELECT t.*,
           COALESCE(sender.id = t.assignee_id, 0) AS self_assigned,
           CASE WHEN sender.username IS NULL OR sender.username = '' THEN '#' || sender.id
                ELSE '@' || sender.username END AS sender_name
    FROM tasks t
    JOIN users sender ON sender.id = COALESCE(t.assigned_by_id, t.user_id)
"""


def get_tasks_by_column(board_id: int, column_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        TASKS_WITH_SENDER + """WHERE t.board_id = ? AND t.column_id = ?
           ORDER BY t.position ASC, t.created_at DESC""",
        (board_id, column_id),
    )
    rows = cur.fetchall()
    conn.close()
    tasks = [dict(r) for r in rows]
    return _attach_tags_to_tasks(tasks)


def get_all_tasks_for_user(user_id: int) -> list[dict]:
    """Used by bot for /list, /all, stats."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*,
                  c.name as col_name, c.key as col_key, b.name as board_name
           FROM tasks t
           LEFT JOIN columns c ON t.column_id = c.id
           LEFT JOIN boards b ON t.board_id = b.id
           WHERE COALESCE(t.assignee_id, t.user_id) = ?
           ORDER BY t.board_id, c.position, c.id, t.position, t.created_at DESC, t.id""",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    tasks = [dict(r) for r in rows]
    return _attach_tags_to_tasks(tasks)


def get_tasks_by_status_bot(user_id: int, col_key: str) -> list[dict]:
    """Bot compat: get tasks where column.key = col_key."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, b.name as board_name, c.name as col_name
           FROM tasks t
           LEFT JOIN columns c ON t.column_id = c.id
           LEFT JOIN boards b ON t.board_id = b.id
           WHERE COALESCE(t.assignee_id, t.user_id) = ? AND c.key = ?
           ORDER BY t.position ASC, t.created_at DESC""",
        (user_id, col_key),
    )
    rows = cur.fetchall()
    conn.close()
    tasks = [dict(r) for r in rows]
    return _attach_tags_to_tasks(tasks)


class InvalidAssignee(ValueError):
    pass


class InvalidDepartment(ValueError):
    pass


def _check_assignee(conn, board_id, assignee_id):
    if assignee_id is not None and (
        type(assignee_id) is not int
        or not 0 < assignee_id <= 2**63 - 1
        or conn.execute(
            f"SELECT 1 FROM ({BOARD_RECIPIENTS}) WHERE board_id = ? AND user_id = ? LIMIT 1",
            (board_id, assignee_id),
        ).fetchone() is None
    ):
        raise InvalidAssignee("Choose an eligible assignee")


def add_task(
    user_id: int,
    board_id: int,
    column_id: int | None,
    title: str,
    description: str = "",
    tag_id: int = None,
    tag_ids: list[int] = None,
    deadline: str = None,
    priority: str = "medium",
    assignee_id: int | None = None,
    *,
    department_id: int | None = None,
) -> dict:
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not _board_has_editor(conn, board_id, user_id):
            raise PermissionError("Board access required")
        if department_id is not None:
            owner_id = conn.execute("SELECT user_id FROM boards WHERE id = ?", (board_id,)).fetchone()["user_id"]
            department = _departments(conn, owner_id, user_id).get(department_id)
            if department is None or (assignee_id is not None and (
                type(assignee_id) is not int or assignee_id not in department["staff"]
            )):
                raise InvalidDepartment("Department or assignee unavailable")
            board_id = department_id
            assignee_id = department["lead_id"] if assignee_id is None else assignee_id
            column_id = None
        else:
            _check_assignee(conn, board_id, assignee_id)
        if column_id is None:
            first = conn.execute("""SELECT id FROM columns WHERE board_id = ?
                                  ORDER BY (key = 'todo') DESC, (key = 'done'), position, id LIMIT 1""", (board_id,)).fetchone()
            if first is None:
                raise ValueError("The board has no columns")
            column_id = first["id"]
        elif conn.execute(
            "SELECT 1 FROM columns WHERE id = ? AND board_id = ?", (column_id, board_id)
        ).fetchone() is None:
            raise ValueError("Choose a column on this board")
        cur = conn.execute(
            """INSERT INTO tasks
               (user_id, board_id, column_id, title, description, tag_id, deadline, priority, assignee_id, assigned_by_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, board_id, column_id, title, description, tag_id, deadline, priority,
                assignee_id, user_id if assignee_id is not None else None,
            ),
        )
        task_id = cur.lastrowid
        resolved_tags = tag_ids or ([tag_id] if tag_id else [])
        if resolved_tags:
            _set_task_tags(conn, task_id, resolved_tags)
        row = conn.execute(TASKS_WITH_SENDER + "WHERE t.id = ?", (task_id,)).fetchone()
    task = dict(row)
    return _attach_tags_to_tasks([task])[0]


def get_task(task_id: int, user_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, c.name AS col_name, b.name AS board_name
           FROM tasks t
           LEFT JOIN columns c ON c.id = t.column_id
           LEFT JOIN boards b ON b.id = t.board_id
           WHERE t.id = ? AND COALESCE(t.assignee_id, t.user_id) = ?""",
        (task_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    task = dict(row)
    return _attach_tags_to_tasks([task])[0]


def update_task(task_id: int, user_id: int, fields: dict, *, tag_ids=None):
    allowed = {"title", "description", "column_id", "priority", "deadline", "assignee_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        original = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if original is None or not _board_has_editor(conn, original["board_id"], user_id):
            return None, None
        if "assignee_id" in updates:
            assignee_id = updates["assignee_id"]
            _check_assignee(conn, original["board_id"], assignee_id)
            if assignee_id is not None and assignee_id != original["assignee_id"]:
                updates["assigned_by_id"] = user_id
        if "column_id" in updates:
            column = conn.execute(
                "SELECT 1 FROM columns WHERE id = ? AND board_id = ?",
                (updates["column_id"], original["board_id"]),
            ).fetchone()
            if column is None:
                raise ValueError("Choose a column on this board")
        if updates:
            set_clause = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", (*updates.values(), task_id))
        if tag_ids is not None:
            _set_task_tags(conn, task_id, tag_ids)
        row = conn.execute(TASKS_WITH_SENDER + "WHERE t.id = ?", (task_id,)).fetchone()
    return _attach_tags_to_tasks([dict(row)])[0], original["assignee_id"]


def move_task(task_id: int, user_id: int, column_id: int) -> bool:
    """Advance a task only to the next column on its board."""
    with closing(get_connection()) as conn, conn:
        cur = conn.execute(
            """UPDATE tasks SET column_id = ?
               WHERE id = ? AND COALESCE(assignee_id, user_id) = ?
                 AND ? = (
                   SELECT target.id FROM columns AS target
                   LEFT JOIN columns AS source ON source.id = tasks.column_id AND source.board_id = tasks.board_id
                   WHERE target.board_id = tasks.board_id
                     AND (source.id IS NULL OR (target.position, target.id) > (source.position, source.id))
                   ORDER BY target.position, target.id LIMIT 1
                 )""",
            (column_id, task_id, user_id, column_id),
        )
        return cur.rowcount > 0


def delete_task(task_id: int, user_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(user_id: int) -> dict:
    """Returns counts grouped by column.key (for bot compat uses todo/in_progress/done keys)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT c.key, COUNT(t.id) as cnt
           FROM tasks t
           JOIN columns c ON t.column_id = c.id
           WHERE COALESCE(t.assignee_id, t.user_id) = ?
           GROUP BY c.key""",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    result = {"todo": 0, "in_progress": 0, "done": 0, "total": 0}
    for r in rows:
        key = r["key"]
        cnt = r["cnt"]
        result["total"] += cnt
        if key in result:
            result[key] += cnt
        else:
            result[key] = cnt
    return result


def get_board_stats(board_id: int) -> dict:
    """Returns task counts for a specific board, grouped by column.key."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT c.key, COUNT(t.id) as cnt
           FROM tasks t
           JOIN columns c ON t.column_id = c.id
           WHERE t.board_id = ?
           GROUP BY c.key""",
        (board_id,),
    )
    rows = cur.fetchall()
    conn.close()
    result = {"todo": 0, "in_progress": 0, "done": 0, "total": 0}
    for r in rows:
        key = r["key"]
        cnt = r["cnt"]
        result["total"] += cnt
        if key in result:
            result[key] += cnt
        else:
            result[key] = cnt
    return result


def get_upcoming_deadlines(hours: int = 24) -> list[dict]:
    """Returns tasks with deadline within next `hours` hours, across all users.

    Deadlines are stored as local-time strings (no timezone). Comparison is
    done in Python using local time to avoid the SQLite datetime('now') UTC bug.
    """
    from datetime import timedelta
    now     = datetime.now()
    cutoff  = now + timedelta(hours=hours)
    now_str    = now.strftime("%Y-%m-%d %H:%M")
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, u.telegram_id
           FROM tasks t
           JOIN users u ON COALESCE(t.assignee_id, t.user_id) = u.id
           LEFT JOIN columns c ON c.id = t.column_id
           WHERE t.deadline IS NOT NULL
             AND (c.key IS NULL OR c.key != 'done')
             AND t.deadline > ?
             AND t.deadline <= ?
           ORDER BY t.deadline ASC""",
        (now_str, cutoff_str),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_active_tasks_for_digest() -> list[dict]:
    """Returns all non-done tasks grouped by user, for daily digest."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, u.telegram_id, c.key as col_key, c.name as col_name
           FROM tasks t
           JOIN users u ON COALESCE(t.assignee_id, t.user_id) = u.id
           JOIN columns c ON t.column_id = c.id
           WHERE c.key != 'done'
           ORDER BY u.telegram_id, t.priority DESC, t.deadline ASC""",
    )
    rows = cur.fetchall()
    conn.close()
    tasks = [dict(r) for r in rows]
    return _attach_tags_to_tasks(tasks)
