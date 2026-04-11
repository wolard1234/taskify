import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from database.db import get_or_create_user

router = Router()


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
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
        ],
    ])


@router.message(CommandStart())
async def cmd_start(message: Message):
    get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
    )
    await message.answer(
        f"Привет, <b>{message.from_user.first_name}</b>! 👋\n\n"
        "<b>Taskify</b> — твой личный менеджер задач.\n"
        "Выбери действие:",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
