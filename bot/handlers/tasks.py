import sys, os
from html import escape
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.handlers.start import back_to_menu_kb
from database.db import (
    get_or_create_user, get_or_create_default_board,
    get_all_tasks_for_user,
    add_task, get_columns, move_task, delete_task, get_stats, get_task,
    get_boards, get_tags, set_task_tags,
)

router = Router()

PRIO_LABELS = {"low": "🟢 Низкий", "medium": "🟡 Средний", "high": "🔴 Высокий"}
PRIO_ORDER  = ["low", "medium", "high"]


def _parse_deadline(text: str | None) -> str | None:
    """Accept DD-MM-YYYY or DD-MM-YYYY HH:MM, return ISO 'YYYY-MM-DD HH:MM' or None."""
    if not text:
        return None
    import re
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}:\d{2}))?$", text.strip())
    if not m:
        return None
    day, month, year, time = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"{year}-{month}-{day} {time}" if time else f"{year}-{month}-{day} 00:00"


def _fmt_dl_display(iso: str | None) -> str:
    """'YYYY-MM-DD HH:MM' → 'DD.MM.YYYY HH:MM'"""
    if not iso:
        return ""
    import re
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}))?", iso)
    if not m:
        return iso
    y, mo, d, t = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"{d}.{mo}.{y} {t}" if t else f"{d}.{mo}.{y}"


# ── FSM states ────────────────────────────────────────────────────────────────
class AddTask(StatesGroup):
    waiting_board    = State()
    waiting_title    = State()
    waiting_priority = State()
    waiting_deadline = State()
    waiting_tags     = State()


# ── Keyboards ─────────────────────────────────────────────────────────────────
def prio_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 Низкий",   callback_data="prio:low"),
            InlineKeyboardButton(text="🟡 Средний",  callback_data="prio:medium"),
            InlineKeyboardButton(text="🔴 Высокий",  callback_data="prio:high"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="prio:cancel")],
    ])


def deadline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить (без дедлайна)", callback_data="dl:skip")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="dl:cancel")],
    ])


def tags_kb(user_id: int, selected_ids: list[int] = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for tag selection. Selected tags shown with checkmark."""
    selected_ids = selected_ids or []
    all_tags = get_tags(user_id)
    rows = []
    for t in all_tags:
        prefix = "✅ " if t["id"] in selected_ids else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}🏷 {t['name']}",
            callback_data=f"tag:toggle:{t['id']}"
        )])
    rows.append([InlineKeyboardButton(text="✅ Готово — сохранить", callback_data="tag:done")])
    rows.append([InlineKeyboardButton(text="⏭ Пропустить (без тегов)", callback_data="tag:skip")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="tag:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task_actions_kb(task_id: int, current_col_key: str, can_delete: bool) -> InlineKeyboardMarkup:
    """Buttons: move to doing / done / delete, depending on current column key."""
    rows = []
    if current_col_key != "in_progress":
        rows.append(InlineKeyboardButton(text="⚙️ В процессе", callback_data=f"task:doing:{task_id}"))
    if current_col_key != "done":
        rows.append(InlineKeyboardButton(text="✅ Готово",     callback_data=f"task:done:{task_id}"))
    kb = []
    if rows:
        kb.append(rows)
    footer = []
    if can_delete:
        footer.append(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task:delete:{task_id}"))
    footer.append(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:list"))
    kb.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fmt_short(t: dict) -> str:
    prio = PRIO_LABELS.get(t.get("priority", "medium"), "")
    dl   = f" 📅 {_fmt_dl_display(t['deadline'])}" if t.get("deadline") else ""
    return f"<code>#{t['id']}</code> <b>{escape(t['title'])}</b> {prio}{dl}"


def _fmt_full(t: dict) -> str:
    prio = PRIO_LABELS.get(t.get("priority", "medium"), "")
    tags = t.get("tags", [])
    tag_str = ""
    if tags:
        tag_str = "\n🏷 " + ", ".join(escape(tg["name"]) for tg in tags)
    dl   = f"\n📅 {_fmt_dl_display(t['deadline'])}" if t.get("deadline") else ""
    col  = f"\n📂 {escape(t['col_name'])}" if t.get("col_name") else ""
    return f"<code>#{t['id']}</code> <b>{escape(t['title'])}</b>\n{prio}{tag_str}{dl}{col}"


def active_tasks(user_id: int) -> list[dict]:
    tasks = (task for task in get_all_tasks_for_user(user_id) if task["col_key"] != "done")
    return sorted(tasks, key=lambda task: {"todo": 0, "in_progress": 1}.get(task["col_key"], 2))


def format_active_tasks(tasks: list[dict]) -> str:
    groups = {}
    for task in tasks:
        heading = {
            "todo": "📋 К выполнению",
            "in_progress": "⚙️ В процессе",
        }.get(task["col_key"], task["col_name"] or "Без столбца")
        groups.setdefault(heading, []).append(_fmt_short(task))
    return "\n\n".join(
        "\n".join([f"<b>{escape(heading)}:</b>", *lines]) for heading, lines in groups.items()
    )


def _parse_add(text: str):
    parts = [p.strip() for p in text.split("|")]
    title    = parts[0] if parts else ""
    priority = parts[1].lower() if len(parts) > 1 else "medium"
    deadline_raw = parts[2] if len(parts) > 2 else None
    if priority not in ("low", "medium", "high"):
        priority = "medium"
    deadline_iso = _parse_deadline(deadline_raw) if deadline_raw else None
    return title, priority, deadline_iso


# ── /add command (legacy shortcut with pipe syntax) ───────────────────────────
@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    raw = message.text.split(maxsplit=1)
    if len(raw) >= 2 and raw[1].strip():
        # direct add with pipe format
        user  = get_or_create_user(message.from_user.id, message.from_user.username or "")
        board = get_or_create_default_board(user["id"])
        cols  = get_columns(board["id"])
        title, priority, deadline = _parse_add(raw[1])
        if not title:
            await message.answer("Название задачи не может быть пустым.")
            return
        col = cols[0] if cols else None
        if not col:
            await message.answer("Нет столбцов в доске. Создайте их в веб-панели.")
            return
        task = add_task(user["id"], board["id"], col["id"], title, priority=priority, deadline=deadline)
        dl_text = f"\n📅 {_fmt_dl_display(deadline)}" if deadline else ""
        await message.answer(
            f"✅ Задача добавлена! <code>#{task['id']}</code>\n"
            f"<b>{title}</b>\n"
            f"Приоритет: {PRIO_LABELS.get(priority, '')}{dl_text}\n"
            f"📋 Доска: <b>{board['name']}</b>",
            parse_mode="HTML",
            reply_markup=back_to_menu_kb(),
        )
    else:
        # start FSM flow — show board selection first
        user   = get_or_create_user(message.from_user.id, message.from_user.username or "")
        boards = get_boards(user["id"])
        if not boards:
            board = get_or_create_default_board(user["id"])
            boards = [board]
        if len(boards) == 1:
            await state.update_data(board_id=boards[0]["id"], board_name=boards[0]["name"])
            await state.set_state(AddTask.waiting_title)
            await message.answer(
                f"📋 Доска: <b>{boards[0]['name']}</b>\n\n✏️ Введи название задачи:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel")]
                ]),
            )
        else:
            await state.set_state(AddTask.waiting_board)
            kb_rows = [[InlineKeyboardButton(
                text=f"📋 {b['name']}",
                callback_data=f"addboard:{b['id']}"
            )] for b in boards]
            kb_rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel")])
            await message.answer(
                "✏️ <b>Новая задача</b>\n\nВыбери доску:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
            )


# ── Menu callbacks ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "menu:add")
async def cb_menu_add(call: CallbackQuery, state: FSMContext):
    user   = get_or_create_user(call.from_user.id, call.from_user.username or "")
    boards = get_boards(user["id"])
    if not boards:
        # auto-create default board and skip selection
        board = get_or_create_default_board(user["id"])
        await state.update_data(board_id=board["id"], board_name=board["name"])
        await state.set_state(AddTask.waiting_title)
        await call.message.edit_text(
            f"📋 Доска: <b>{board['name']}</b>\n\n✏️ Введи название задачи:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel")]
            ]),
        )
    elif len(boards) == 1:
        # single board — skip selection
        await state.update_data(board_id=boards[0]["id"], board_name=boards[0]["name"])
        await state.set_state(AddTask.waiting_title)
        await call.message.edit_text(
            f"📋 Доска: <b>{boards[0]['name']}</b>\n\n✏️ Введи название задачи:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel")]
            ]),
        )
    else:
        await state.set_state(AddTask.waiting_board)
        kb_rows = [[InlineKeyboardButton(
            text=f"📋 {b['name']}",
            callback_data=f"addboard:{b['id']}"
        )] for b in boards]
        kb_rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel")])
        await call.message.edit_text(
            "✏️ <b>Новая задача</b>\n\nВыбери доску:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        )
    await call.answer()


@router.callback_query(F.data == "menu:list")
async def cb_menu_list(call: CallbackQuery):
    user = get_or_create_user(call.from_user.id, call.from_user.username or "")
    tasks = active_tasks(user["id"])

    if not tasks:
        await call.message.edit_text(
            "Нет активных задач. Добавь первую!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="menu:add")],
                [InlineKeyboardButton(text="◀️ Меню",           callback_data="menu:main")],
            ]),
        )
        await call.answer()
        return

    kb_rows = [[InlineKeyboardButton(
        text=f"#{t['id']} {t['title'][:22]}",
        callback_data=f"task:view:{t['id']}"
    )] for t in tasks[:8]]
    kb_rows.append([InlineKeyboardButton(text="◀️ Меню", callback_data="menu:main")])

    await call.message.edit_text(
        format_active_tasks(tasks),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
    await call.answer()


@router.callback_query(F.data == "menu:all")
async def cb_menu_all(call: CallbackQuery):
    user  = get_or_create_user(call.from_user.id, call.from_user.username or "")
    tasks = get_all_tasks_for_user(user["id"])
    if not tasks:
        await call.message.edit_text(
            "Задач пока нет.",
            reply_markup=back_to_menu_kb(),
        )
        await call.answer()
        return

    boards_map: dict[str, list] = {}
    for t in tasks:
        key = t.get("board_name") or "Без доски"
        boards_map.setdefault(key, []).append(t)

    lines = []
    for bname, btasks in boards_map.items():
        lines.append(f"\n<b>📋 {escape(bname)}:</b>")
        lines += [_fmt_short(t) for t in btasks]

    await call.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "menu:stats")
async def cb_menu_stats(call: CallbackQuery):
    user = get_or_create_user(call.from_user.id, call.from_user.username or "")
    s = get_stats(user["id"])
    await call.message.edit_text(
        "<b>📊 Статистика:</b>\n\n"
        f"К выполнению:  <b>{s['todo']}</b>\n"
        f"В процессе:    <b>{s['in_progress']}</b>\n"
        f"Готово:        <b>{s['done']}</b>\n"
        f"Всего:         <b>{s['total']}</b>",
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "menu:web")
async def cb_menu_web(call: CallbackQuery):
    web_url = os.getenv("WEB_URL", "http://localhost:5000")
    token   = str(call.from_user.id)
    login_url = f"{web_url}/login?token={token}"
    # Send as a new message so the link is always delivered
    await call.message.answer(
        f"🌐 <b>Веб-панель ЦККО</b>\n\n"
        f'<a href="{login_url}">{login_url}</a>\n\n'
        "<i>Ссылка привязана к твоему аккаунту. Не передавай её другим.</i>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


# ── Task view / actions ────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("task:view:"))
async def cb_task_view(call: CallbackQuery):
    user    = get_or_create_user(call.from_user.id, call.from_user.username or "")
    task_id = int(call.data.split(":")[2])
    task    = get_task(task_id, user["id"])
    if not task:
        await call.answer("Задача не найдена.", show_alert=True)
        return
    # determine col key
    cols    = get_columns(task["board_id"])
    col     = next((c for c in cols if c["id"] == task["column_id"]), None)
    col_key = col["key"] if col and col.get("key") else "todo"

    await call.message.edit_text(
        _fmt_full(task),
        parse_mode="HTML",
        reply_markup=task_actions_kb(task_id, col_key, task["user_id"] == user["id"]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("task:doing:"))
@router.callback_query(F.data.startswith("task:done:"))
async def cb_task_move(call: CallbackQuery):
    user = get_or_create_user(call.from_user.id, call.from_user.username or "")
    _, action, raw_task_id = call.data.split(":")
    task_id = int(raw_task_id)
    task = get_task(task_id, user["id"])
    if not task:
        await call.answer("Задача не найдена.", show_alert=True)
        return
    columns = get_columns(task["board_id"])
    if not columns:
        await call.answer("Столбцы задачи недоступны.", show_alert=True)
        return
    key = "done" if action == "done" else "in_progress"
    fallback = columns[-1] if action == "done" else columns[min(1, len(columns) - 1)]
    column = next((column for column in columns if column["key"] == key), fallback)
    if not move_task(task_id, user["id"], column["id"]):
        await call.answer("Задача больше недоступна.", show_alert=True)
        return
    task["col_name"] = column["name"]
    await call.answer(f"Задача перемещена в «{column['name']}»")
    await call.message.edit_text(
        _fmt_full(task),
        parse_mode="HTML",
        reply_markup=task_actions_kb(task_id, key, task["user_id"] == user["id"]),
    )


@router.callback_query(F.data.startswith("task:delete:"))
async def cb_task_delete(call: CallbackQuery):
    user    = get_or_create_user(call.from_user.id, call.from_user.username or "")
    task_id = int(call.data.split(":")[2])
    ok = delete_task(task_id, user["id"])
    if ok:
        await call.message.edit_text(
            f"🗑 Задача <code>#{task_id}</code> удалена.",
            parse_mode="HTML",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await call.answer("Задача не найдена.", show_alert=True)
        return
    await call.answer()


# ── FSM: add task flow ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "add:cancel")
async def cb_add_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Добавление отменено.", reply_markup=back_to_menu_kb())
    await call.answer()


@router.callback_query(AddTask.waiting_board, F.data.startswith("addboard:"))
async def fsm_got_board(call: CallbackQuery, state: FSMContext):
    board_id = int(call.data.split(":")[1])
    user     = get_or_create_user(call.from_user.id, call.from_user.username or "")
    boards   = get_boards(user["id"])
    board    = next((b for b in boards if b["id"] == board_id), None)
    if not board:
        await call.answer("Доска не найдена.", show_alert=True)
        return
    await state.update_data(board_id=board["id"], board_name=board["name"])
    await state.set_state(AddTask.waiting_title)
    await call.message.edit_text(
        f"📋 Доска: <b>{board['name']}</b>\n\n✏️ Введи название задачи:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="add:cancel")]
        ]),
    )
    await call.answer()


@router.message(AddTask.waiting_title)
async def fsm_got_title(message: Message, state: FSMContext):
    title = message.text.strip() if message.text else ""
    if not title:
        await message.answer("Название не может быть пустым. Попробуй снова:")
        return
    await state.update_data(title=title)
    await state.set_state(AddTask.waiting_priority)
    await message.answer(
        f"Задача: <b>{title}</b>\n\nВыбери приоритет:",
        parse_mode="HTML",
        reply_markup=prio_kb(),
    )


@router.callback_query(AddTask.waiting_priority, F.data.startswith("prio:"))
async def fsm_got_priority(call: CallbackQuery, state: FSMContext):
    prio = call.data.split(":")[1]
    if prio == "cancel":
        await state.clear()
        await call.message.edit_text("Добавление отменено.", reply_markup=back_to_menu_kb())
        await call.answer()
        return
    await state.update_data(priority=prio)
    await state.set_state(AddTask.waiting_deadline)
    await call.message.edit_text(
        f"Приоритет: {PRIO_LABELS.get(prio, prio)}\n\n"
        "Введи дедлайн в формате <code>ДД-ММ-ГГГГ</code> или <code>ДД-ММ-ГГГГ ЧЧ:ММ</code>\n"
        "или нажми «Пропустить»:",
        parse_mode="HTML",
        reply_markup=deadline_kb(),
    )
    await call.answer()


@router.callback_query(AddTask.waiting_deadline, F.data == "dl:skip")
async def fsm_deadline_skip(call: CallbackQuery, state: FSMContext):
    await state.update_data(deadline=None)
    user = get_or_create_user(call.from_user.id, call.from_user.username or "")
    all_tags = get_tags(user["id"])
    if not all_tags:
        # no tags exist, skip tag step entirely
        await _finish_add(call.message, state, deadline=None, tag_ids=[], edit=True)
    else:
        await state.set_state(AddTask.waiting_tags)
        await state.update_data(selected_tag_ids=[])
        await call.message.edit_text(
            "🏷 Выбери теги (можно несколько):",
            reply_markup=tags_kb(user["id"], []),
        )
    await call.answer()


@router.callback_query(AddTask.waiting_deadline, F.data == "dl:cancel")
async def fsm_deadline_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Добавление отменено.", reply_markup=back_to_menu_kb())
    await call.answer()


@router.message(AddTask.waiting_deadline)
async def fsm_got_deadline(message: Message, state: FSMContext):
    deadline_raw = message.text.strip() if message.text else None
    deadline_iso = _parse_deadline(deadline_raw)
    if deadline_raw and deadline_iso is None:
        await message.answer(
            "Неверный формат. Используй <code>ДД-ММ-ГГГГ</code> или <code>ДД-ММ-ГГГГ ЧЧ:ММ</code>:",
            parse_mode="HTML",
            reply_markup=deadline_kb(),
        )
        return
    await state.update_data(deadline=deadline_iso)
    user = get_or_create_user(message.from_user.id, message.from_user.username or "")
    all_tags = get_tags(user["id"])
    if not all_tags:
        await _finish_add(message, state, deadline=deadline_iso, tag_ids=[], edit=False)
    else:
        await state.set_state(AddTask.waiting_tags)
        await state.update_data(selected_tag_ids=[])
        await message.answer(
            "🏷 Выбери теги (можно несколько):",
            reply_markup=tags_kb(user["id"], []),
        )


# ── FSM: tag selection ─────────────────────────────────────────────────────────
@router.callback_query(AddTask.waiting_tags, F.data.startswith("tag:toggle:"))
async def fsm_tag_toggle(call: CallbackQuery, state: FSMContext):
    tag_id = int(call.data.split(":")[2])
    data = await state.get_data()
    selected = data.get("selected_tag_ids", [])
    if tag_id in selected:
        selected.remove(tag_id)
    else:
        selected.append(tag_id)
    await state.update_data(selected_tag_ids=selected)
    user = get_or_create_user(call.from_user.id, call.from_user.username or "")
    await call.message.edit_reply_markup(reply_markup=tags_kb(user["id"], selected))
    await call.answer()


@router.callback_query(AddTask.waiting_tags, F.data == "tag:done")
async def fsm_tag_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_tag_ids", [])
    deadline = data.get("deadline")
    await _finish_add(call.message, state, deadline=deadline, tag_ids=selected, edit=True)
    await call.answer()


@router.callback_query(AddTask.waiting_tags, F.data == "tag:skip")
async def fsm_tag_skip(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    deadline = data.get("deadline")
    await _finish_add(call.message, state, deadline=deadline, tag_ids=[], edit=True)
    await call.answer()


@router.callback_query(AddTask.waiting_tags, F.data == "tag:cancel")
async def fsm_tag_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Добавление отменено.", reply_markup=back_to_menu_kb())
    await call.answer()


async def _finish_add(msg, state: FSMContext, deadline, tag_ids: list[int] = None, edit: bool = True):
    data  = await state.get_data()
    title    = data.get("title", "")
    priority = data.get("priority", "medium")
    board_id = data.get("board_id")
    board_name = data.get("board_name", "")
    await state.clear()

    tg_id  = msg.chat.id
    username = ""
    user  = get_or_create_user(tg_id, username)

    # use selected board or fallback to default
    if not board_id:
        board = get_or_create_default_board(user["id"])
        board_id   = board["id"]
        board_name = board["name"]

    cols  = get_columns(board_id)
    col   = cols[0] if cols else None
    if not col:
        text = "Нет столбцов в доске. Создайте их в веб-панели."
        if edit:
            await msg.edit_text(text, reply_markup=back_to_menu_kb())
        else:
            await msg.answer(text, reply_markup=back_to_menu_kb())
        return

    task = add_task(user["id"], board_id, col["id"], title, priority=priority, deadline=deadline, tag_ids=tag_ids or [])

    dl_txt = f"\n📅 {_fmt_dl_display(deadline)}" if deadline else ""
    tags_txt = ""
    if task.get("tags"):
        tags_txt = "\n🏷 " + ", ".join(tg["name"] for tg in task["tags"])
    text   = (
        f"✅ Задача добавлена! <code>#{task['id']}</code>\n"
        f"<b>{title}</b>\n"
        f"Приоритет: {PRIO_LABELS.get(priority, '')}{dl_txt}{tags_txt}\n"
        f"📋 Доска: <b>{board_name}</b>"
    )
    if edit:
        await msg.edit_text(text, parse_mode="HTML", reply_markup=back_to_menu_kb())
    else:
        await msg.answer(text, parse_mode="HTML", reply_markup=back_to_menu_kb())


# ── Legacy text commands (kept as shortcuts) ───────────────────────────────────
@router.message(Command("list"))
async def cmd_list(message: Message):
    user = get_or_create_user(message.from_user.id, message.from_user.username or "")
    tasks = active_tasks(user["id"])
    if not tasks:
        await message.answer("Нет активных задач.", reply_markup=back_to_menu_kb())
        return
    await message.answer(format_active_tasks(tasks), parse_mode="HTML", reply_markup=back_to_menu_kb())


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    user = get_or_create_user(message.from_user.id, message.from_user.username or "")
    s = get_stats(user["id"])
    await message.answer(
        "<b>📊 Статистика:</b>\n\n"
        f"К выполнению:  <b>{s['todo']}</b>\n"
        f"В процессе:    <b>{s['in_progress']}</b>\n"
        f"Готово:        <b>{s['done']}</b>\n"
        f"Всего:         <b>{s['total']}</b>",
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )


@router.message(Command("web"))
async def cmd_web(message: Message):
    get_or_create_user(message.from_user.id, message.from_user.username or "")
    web_url = os.getenv("WEB_URL", "http://localhost:5000")
    token   = str(message.from_user.id)
    login_url = f"{web_url}/login?token={token}"
    await message.answer(
        f"🌐 <b>Веб-панель ЦККО</b>\n"
        f"{login_url}\n\n"
        "<i>Не передавай ссылку другим.</i>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=back_to_menu_kb(),
    )
