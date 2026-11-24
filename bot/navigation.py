from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.db import is_latest_telegram_message, record_telegram_message


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")]
    ])


async def respond(target: Message | CallbackQuery, text: str, **kwargs):
    if isinstance(target, Message):
        return await target.answer(text, **kwargs)

    message = target.message
    if isinstance(message, Message) and is_latest_telegram_message(message.chat.id, message.message_id):
        try:
            return await message.edit_text(text, **kwargs)
        except TelegramBadRequest as exc:
            error = exc.message.lower()
            if "message is not modified" in error:
                return
            if "message can't be edited" not in error and "message to edit not found" not in error:
                raise

    return await target.bot.send_message(target.from_user.id, text, **kwargs)


async def track_sent_messages(make_request, bot, method):
    result = await make_request(bot, method)
    if isinstance(method, SendMessage) and isinstance(result, Message) and result.chat.type == ChatType.PRIVATE:
        record_telegram_message(result.chat.id, result.message_id)
    return result
