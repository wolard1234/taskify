import sys, os
from html import escape
from itertools import groupby
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.navigation import back_to_menu_kb, respond
from database.db import (
    get_or_create_user, get_or_create_default_board,
    get_all_tasks_for_user,
    add_task, get_columns, move_task, delete_task, get_stats, get_task,
    get_boards, get_tags, set_task_tags,
)

router = Router()

PRIO_LABELS = {"low": "🟢 Низкий", "medium": "🟡 Средний", "high": "🔴 Высокий"}
PRIO_ORDER  = ["low", "medium", "high"]
TAG_PROMPT = "🏷 Выбери теги (можно несколько):"


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


def task_actions_kb(task_id: int, next_column: dict | None, can_delete: bool, source: str) -> InlineKeyboardMarkup:
    kb = []
    if next_column is not None:
        suffix = f":{source}" if source else ""
        kb.append([InlineKeyboardButton(
            text=next_column["name"], callback_data=f"task:move:{task_id}:{next_column['id']}{suffix}",
        )])
    footer = []
    if can_delete:
        footer.append(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"task:delete:{task_id}"))
    footer.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"menu:{source or 'list'}"))
    kb.append(footer)
    kb.extend(back_to_menu_kb().inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fmt_short(t: dict) -> str:
    prio = PRIO_LABELS.get(t.get("priority", "medium"), "")
    dl   = f" 📅 {_fmt_dl_display(t['deadline'])}" if t.get("deadline") else ""
    title = t["title"]
    if len(title) > 120:
        title = title[:119] + "…"
    return f"<code>#{t['id']}</code> <b>{escape(title)}</b> {prio}{dl}"


def _fmt_full(t: dict) -> str:
    prio = PRIO_LABELS.get(t.get("priority", "medium"), "")
    tags = t.get("tags", [])
    tag_str = ""
    if tags:
        tag_str = "\n🏷 " + ", ".join(escape(tg["name"]) for tg in tags)
    dl   = f"\n📅 {_fmt_dl_display(t['deadline'])}" if t.get("deadline") else ""
    board = f"\n📋 Доска: <b>{escape(t['board_name'])}</b>" if t["board_name"] else ""
    col  = f"\n📂 {escape(t['col_name'])}" if t.get("col_name") else ""
    return f"<code>#{t['id']}</code> <b>{escape(t['title'])}</b>\n{prio}{tag_str}{dl}{board}{col}"


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
        await respond(
            call,
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
        await respond(
            call,
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
        await respond(
            call,
            "✏️ <b>Новая задача</b>\n\nВыбери доску:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        )
    await call.answer()


@router.callback_query(F.data.regexp(r"^menu:(?:list|all)(?::[0-9]{1,9})?$"))
async def cb_menu_tasks(call: CallbackQuery, user: dict):
    _, kind, *page = call.data.split(":")
    await show_task_list(call, user["id"], kind, int(page[0]) if page else 0)
    await call.answer()


async def show_task_list(target: Message | CallbackQuery, user_id: int, kind: str, page: int):
    tasks = get_all_tasks_for_user(user_id)
    if kind == "list":
        tasks = [task for task in tasks if task["assignee_id"] == user_id and task["col_key"] != "done"]
    if not tasks:
        await respond(
            target,
            "Тебе не назначено активных задач." if kind == "list" else "Задач пока нет.",
            reply_markup=back_to_menu_kb(),
        )
        return

    page_size = 8
    last_page = (len(tasks) - 1) // page_size
    page = min(page, last_page)
    visible = tasks[page * page_size:(page + 1) * page_size]
    lines = []
    for (_, board_name), board_tasks in groupby(visible, key=lambda t: (t["board_id"], t["board_name"])):
        lines.append(f"<b>📋 {escape(board_name or 'Без доски')}:</b>")
        for (_, column_name), column_tasks in groupby(board_tasks, key=lambda t: (t["column_id"], t["col_name"])):
            lines.append(f"📂 {escape(column_name or 'Без столбца')}")
            lines.extend(_fmt_short(task) for task in column_tasks)
        lines.append("")

    rows = [[InlineKeyboardButton(
        text=f"#{task['id']} {task['title'][:36]}",
        callback_data=f"task:view:{task['id']}:{kind}:{page}",
    )] for task in visible]
    if last_page:
        lines.append(f"Страница {page + 1} из {last_page + 1}")
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"menu:{kind}:{destination}")
            for label, destination in (("⬅️ Предыдущая", page - 1), ("Следующая ➡️", page + 1))
            if 0 <= destination <= last_page
        ])
    rows.extend(back_to_menu_kb().inline_keyboard)
    await respond(
        target,
        "\n".join(lines).strip(),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "menu:stats")
async def cb_menu_stats(call: CallbackQuery):
    user = get_or_create_user(call.from_user.id, call.from_user.username or "")
    s = get_stats(user["id"])
    await respond(
        call,
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
    await respond(
        call,
        f"🌐 <b>Веб-панель ЦККО</b>\n\n"
        f'<a href="{login_url}">{login_url}</a>\n\n'
        "<i>Ссылка привязана к твоему аккаунту. Не передавай её другим.</i>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


# ── Task view / actions ────────────────────────────────────────────────────────
@router.callback_query(F.data.regexp(r"^task:(?:(?:view|doing|done):[0-9]{1,19}|move:[0-9]{1,19}:[0-9]{1,19})(?::(?:list|all):[0-9]{1,9})?$"))
async def cb_task_view(call: CallbackQuery, user: dict):
    _, action, *ids = call.data.split(":")
    id_count = 2 if action == "move" else 1
    task_id, *target = map(int, ids[:id_count])
    source = ":".join(ids[id_count:])
    if task_id > 2**63 - 1 or any(column_id > 2**63 - 1 for column_id in target):
        await call.answer("Задача недоступна.", show_alert=True)
        return
    moved = action == "move" and move_task(task_id, user["id"], target[0])
    task = get_task(task_id, user["id"])
    if not task:
        await call.answer("Задача не найдена.", show_alert=True)
        return
    columns = get_columns(task["board_id"])
    next_index = next((i + 1 for i, column in enumerate(columns) if column["id"] == task["column_id"]), 0)
    next_column = columns[next_index] if next_index < len(columns) else None
    feedback = None
    if moved and task["col_name"]:
        feedback = f"Задача перемещена в «{task['col_name']}»"
    elif action != "view":
        feedback = "Следующий этап изменился." if next_column else "Следующего этапа нет."
    await respond(
        call,
        _fmt_full(task),
        parse_mode="HTML",
        reply_markup=task_actions_kb(task_id, next_column, task["user_id"] == user["id"], source),
    )
    await call.answer(feedback)


@router.callback_query(F.data.startswith("task:delete:"))
async def cb_task_delete(call: CallbackQuery):
    user    = get_or_create_user(call.from_user.id, call.from_user.username or "")
    task_id = int(call.data.split(":")[2])
    ok = delete_task(task_id, user["id"])
    if ok:
        await respond(
            call,
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
    await respond(call, "Добавление отменено.", reply_markup=back_to_menu_kb())
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
    await respond(
        call,
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
        await respond(call, "Добавление отменено.", reply_markup=back_to_menu_kb())
        await call.answer()
        return
    await state.update_data(priority=prio)
    await state.set_state(AddTask.waiting_deadline)
    await respond(
        call,
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
        await _finish_add(call, state, deadline=None, tag_ids=[])
    else:
        await state.set_state(AddTask.waiting_tags)
        await state.update_data(selected_tag_ids=[])
        await respond(call, TAG_PROMPT, reply_markup=tags_kb(user["id"], []))
    await call.answer()


@router.callback_query(AddTask.waiting_deadline, F.data == "dl:cancel")
async def fsm_deadline_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await respond(call, "Добавление отменено.", reply_markup=back_to_menu_kb())
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
        await _finish_add(message, state, deadline=deadline_iso, tag_ids=[])
    else:
        await state.set_state(AddTask.waiting_tags)
        await state.update_data(selected_tag_ids=[])
        await message.answer(
            TAG_PROMPT,
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
    await respond(call, TAG_PROMPT, reply_markup=tags_kb(user["id"], selected))
    await call.answer()


@router.callback_query(AddTask.waiting_tags, F.data == "tag:done")
async def fsm_tag_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_tag_ids", [])
    deadline = data.get("deadline")
    await _finish_add(call, state, deadline=deadline, tag_ids=selected)
    await call.answer()


@router.callback_query(AddTask.waiting_tags, F.data == "tag:skip")
async def fsm_tag_skip(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    deadline = data.get("deadline")
    await _finish_add(call, state, deadline=deadline, tag_ids=[])
    await call.answer()


@router.callback_query(AddTask.waiting_tags, F.data == "tag:cancel")
async def fsm_tag_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await respond(call, "Добавление отменено.", reply_markup=back_to_menu_kb())
    await call.answer()


async def _finish_add(target: Message | CallbackQuery, state: FSMContext, deadline, tag_ids: list[int]):
    data  = await state.get_data()
    title    = data.get("title", "")
    priority = data.get("priority", "medium")
    board_id = data.get("board_id")
    board_name = data.get("board_name", "")
    await state.clear()

    user = get_or_create_user(state.key.chat_id)

    # use selected board or fallback to default
    if not board_id:
        board = get_or_create_default_board(user["id"])
        board_id   = board["id"]
        board_name = board["name"]

    cols  = get_columns(board_id)
    col   = cols[0] if cols else None
    if not col:
        text = "Нет столбцов в доске. Создайте их в веб-панели."
        await respond(target, text, reply_markup=back_to_menu_kb())
        return

    task = add_task(user["id"], board_id, col["id"], title, priority=priority, deadline=deadline, tag_ids=tag_ids)

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
    await respond(target, text, parse_mode="HTML", reply_markup=back_to_menu_kb())


# ── Legacy text commands (kept as shortcuts) ───────────────────────────────────
@router.message(Command("list"))
async def cmd_list(message: Message, user: dict):
    await show_task_list(message, user["id"], "list", 0)


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
