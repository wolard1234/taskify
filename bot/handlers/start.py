import os
import re
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.db import get_board_stats, get_or_create_user, get_registration_departments, register_user

router = Router()
ROLES = {"employee": "Сотрудник", "lead": "Лид отдела", "admin": "Администратор"}


class Registration(StatesGroup):
    full_name = State()


def role_for(user: dict, departments: list[dict]) -> str:
    admins = os.getenv("ADMIN_TELEGRAM_IDS", "").split(",")
    if str(user["telegram_id"]) in {value.strip() for value in admins}:
        return "admin"
    if any(department["department_lead_id"] == user["id"] for department in departments):
        return "lead"
    return "employee"


def main_menu_kb(user: dict) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📋 Мои задачи",   callback_data="menu:list"),
            InlineKeyboardButton(text="➕ Добавить",      callback_data="menu:add"),
        ],
        [
            InlineKeyboardButton(text="✅ Все задачи",   callback_data="menu:all"),
            InlineKeyboardButton(text="📊 Статистика",   callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton(text="🌐 Веб-панель",   callback_data="menu:web"),
            InlineKeyboardButton(text="Мой профиль", callback_data="menu:profile"),
        ],
    ]
    role = role_for(user, get_registration_departments())
    if role != "employee":
        rows.append([InlineKeyboardButton(
            text="Все отделы" if role == "admin" else "Мои отделы",
            callback_data="menu:departments",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")]
    ])


async def send_main_menu(message: Message, user: dict):
    await message.answer(
        f"Привет, <b>{escape(user['full_name'])}</b>! 👋\n\n"
        "<b>ЦККО</b> — твой менеджер задач.\n"
        "Выбери действие:",
        parse_mode="HTML",
        reply_markup=main_menu_kb(user),
    )


async def registration_gate(handler, event: Message | CallbackQuery, data: dict):
    message = event.message if isinstance(event, CallbackQuery) else event
    if not isinstance(message, Message) or message.chat.type != ChatType.PRIVATE or not event.from_user:
        if isinstance(event, CallbackQuery):
            await event.answer("Открой бота в личном чате.", show_alert=True)
        return

    actor = event.from_user
    user = get_or_create_user(actor.id, actor.username or "")
    if user["full_name"] and user["department_id"] is not None:
        data["user"] = user
        return await handler(event, data)

    state: FSMContext = data["state"]
    if isinstance(event, Message) and await state.get_state() == Registration.full_name.state:
        parts = (event.text or "").split()
        if not (parts and parts[0].partition("@")[0] == "/start"):
            full_name = " ".join(parts)
            if len(parts) < 2 or len(full_name) > 120 or not all(
                re.fullmatch(r"[^\W\d_]+(?:[-’'][^\W\d_]+)*", part) for part in parts
            ):
                await message.answer("Введи фамилию и имя, а также отчество, если есть. Например: Иванов Иван Иванович.")
                return
            department_id = (await state.get_data())["department_id"]
            if register_user(user["id"], department_id, full_name):
                await state.clear()
                await send_main_menu(message, {**user, "department_id": department_id, "full_name": full_name})
                return
            await message.answer("Выбранный отдел больше недоступен. Выбери отдел заново.")

    departments = get_registration_departments()
    if isinstance(event, CallbackQuery):
        department = next((entry for entry in departments if event.data == f"reg:department:{entry['id']}"), None)
        if department:
            await state.set_data({"department_id": department["id"]})
            await state.set_state(Registration.full_name)
            await event.answer()
            await message.answer(
                f"Отдел: <b>{escape(department['name'])}</b>\n\n"
                "Введи фамилию, имя и отчество (если есть) одним сообщением.",
                parse_mode="HTML",
            )
            return
        if await state.get_state() == Registration.full_name.state and not (event.data or "").startswith("reg:"):
            await event.answer("Сначала введи ФИО, чтобы закончить регистрацию.", show_alert=True)
            return
        await event.answer("Сначала выбери доступный отдел.")

    await state.clear()
    if not departments:
        await message.answer("Отделы ещё не настроены. Обратись к администратору и попробуй /start позже.")
        return
    await message.answer("Чтобы начать работу, выбери свой отдел:", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=entry["name"], callback_data=f"reg:department:{entry['id']}")]
                         for entry in departments],
    ))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user: dict):
    await state.clear()
    await send_main_menu(message, user)


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(call: CallbackQuery, state: FSMContext, user: dict):
    await state.clear()
    await call.message.edit_text("Выбери действие:", reply_markup=main_menu_kb(user))
    await call.answer()


@router.callback_query(F.data == "menu:profile")
async def cb_menu_profile(call: CallbackQuery, user: dict):
    departments = get_registration_departments()
    department = next((entry["name"] for entry in departments if entry["id"] == user["department_id"]), "Недоступен")
    await call.message.edit_text(
        f"<b>Мой профиль</b>\n\nФИО: {escape(user['full_name'])}\n"
        f"Отдел: {escape(department)}\nРоль: {ROLES[role_for(user, departments)]}",
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "menu:departments")
async def cb_menu_departments(call: CallbackQuery, user: dict):
    departments = get_registration_departments()
    role = role_for(user, departments)
    if role == "employee":
        await call.answer("Раздел доступен лидам и администраторам.", show_alert=True)
        return
    if role == "lead":
        departments = [entry for entry in departments if entry["department_lead_id"] == user["id"]]
    lines = []
    for entry in departments:
        stats = get_board_stats(entry["id"])
        lines.append(f"<b>{escape(entry['name'])}</b>: активных — {stats['total'] - stats['done']}, готово — {stats['done']}")
    await call.message.edit_text(
        "\n".join(lines) if lines else "Отделы ещё не настроены.",
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("reg:"))
async def cb_registration_finished(call: CallbackQuery):
    await call.answer("Регистрация уже завершена.")
