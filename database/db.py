import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "taskify.db")

DEFAULT_COLUMNS = [
    {"key": "todo",        "name_ru": "К выполнению", "name_en": "To Do",       "position": 0},
    {"key": "in_progress", "name_ru": "В процессе",   "name_en": "In Progress",  "position": 1},
    {"key": "done",        "name_ru": "Готово",        "name_en": "Done",         "position": 2},
]


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
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS boards (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name       TEXT NOT NULL DEFAULT 'My Board',
            color      TEXT NOT NULL DEFAULT '#5b6af0',
            position   INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS columns (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id   INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            key        TEXT NOT NULL,
            name       TEXT NOT NULL,
            position   INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    """)
    conn.commit()
    conn.close()


def _migrate():
    """Non-destructive migration: add missing columns/tables if upgrading old DB."""
    conn = get_connection()
    cur = conn.cursor()
    # check if boards table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='boards'")
    if not cur.fetchone():
        conn.close()
        return  # fresh DB, nothing to migrate
    # check if tasks has board_id
    cur.execute("PRAGMA table_info(tasks)")
    cols = {row["name"] for row in cur.fetchall()}
    if "board_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE")
    if "column_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN column_id INTEGER REFERENCES columns(id) ON DELETE SET NULL")
    if "tag_id" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN tag_id INTEGER REFERENCES tags(id) ON DELETE SET NULL")
    # remove old status column if present — NOT removing (safe fallback)
    conn.commit()
    conn.close()


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
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM boards WHERE id = ? AND user_id = ?", (board_id, user_id))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_board(user_id: int, name: str, color: str = "#5b6af0") -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(position),0)+1 FROM boards WHERE user_id = ?", (user_id,))
    pos = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO boards (user_id, name, color, position) VALUES (?, ?, ?, ?)",
        (user_id, name, color, pos),
    )
    conn.commit()
    board_id = cur.lastrowid
    # create default columns for this board
    for col in DEFAULT_COLUMNS:
        cur.execute(
            "INSERT INTO columns (board_id, key, name, position) VALUES (?, ?, ?, ?)",
            (board_id, col["key"], col["name_ru"], col["position"]),
        )
    conn.commit()
    cur.execute("SELECT * FROM boards WHERE id = ?", (board_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row)


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


# ── Columns ───────────────────────────────────────────────────────────────────

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


def add_column(board_id: int, name: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
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


# ── Tasks ─────────────────────────────────────────────────────────────────────

def get_tasks_by_column(board_id: int, column_id: int) -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, tg.name as tag_name, tg.color as tag_color
           FROM tasks t LEFT JOIN tags tg ON t.tag_id = tg.id
           WHERE t.board_id = ? AND t.column_id = ?
           ORDER BY t.position ASC, t.created_at DESC""",
        (board_id, column_id),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_tasks_for_user(user_id: int) -> list[dict]:
    """Used by bot for /list, /all, stats."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, tg.name as tag_name, tg.color as tag_color,
                  c.name as col_name, b.name as board_name
           FROM tasks t
           LEFT JOIN tags tg ON t.tag_id = tg.id
           LEFT JOIN columns c ON t.column_id = c.id
           LEFT JOIN boards b ON t.board_id = b.id
           WHERE t.user_id = ?
           ORDER BY t.board_id, t.position ASC, t.created_at DESC""",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tasks_by_status_bot(user_id: int, col_key: str) -> list[dict]:
    """Bot compat: get tasks where column.key = col_key."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, tg.name as tag_name, b.name as board_name, c.name as col_name
           FROM tasks t
           LEFT JOIN tags tg ON t.tag_id = tg.id
           LEFT JOIN columns c ON t.column_id = c.id
           LEFT JOIN boards b ON t.board_id = b.id
           WHERE t.user_id = ? AND c.key = ?
           ORDER BY t.position ASC, t.created_at DESC""",
        (user_id, col_key),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_task(
    user_id: int,
    board_id: int,
    column_id: int,
    title: str,
    description: str = "",
    tag_id: int = None,
    deadline: str = None,
    priority: str = "medium",
) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tasks (user_id, board_id, column_id, title, description, tag_id, deadline, priority)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, board_id, column_id, title, description, tag_id, deadline, priority),
    )
    conn.commit()
    task_id = cur.lastrowid
    cur.execute(
        """SELECT t.*, tg.name as tag_name, tg.color as tag_color
           FROM tasks t LEFT JOIN tags tg ON t.tag_id = tg.id
           WHERE t.id = ?""",
        (task_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row)


def get_task(task_id: int, user_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.*, tg.name as tag_name, tg.color as tag_color
           FROM tasks t LEFT JOIN tags tg ON t.tag_id = tg.id
           WHERE t.id = ? AND t.user_id = ?""",
        (task_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_task(task_id: int, user_id: int, **fields) -> bool:
    allowed = {"title", "description", "column_id", "priority", "deadline", "tag_id", "position"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id, user_id]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE tasks SET {set_clause} WHERE id = ? AND user_id = ?", values)
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def move_task(task_id: int, user_id: int, column_id: int) -> bool:
    return update_task(task_id, user_id, column_id=column_id)


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
           WHERE t.user_id = ?
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
           JOIN users u ON t.user_id = u.id
           WHERE t.deadline IS NOT NULL
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
           JOIN users u ON t.user_id = u.id
           JOIN columns c ON t.column_id = c.id
           WHERE c.key != 'done'
           ORDER BY u.telegram_id, t.priority DESC, t.deadline ASC""",
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
