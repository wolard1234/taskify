import asyncio, logging, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from dotenv import load_dotenv

from database.db import init_db
from bot.handlers import start, tasks
from bot.navigation import track_sent_messages
from bot.scheduler import setup_scheduler

load_dotenv()

def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    dp.message.outer_middleware(start.registration_gate)
    dp.callback_query.outer_middleware(start.registration_gate)
    dp.include_router(start.router)
    dp.include_router(tasks.router)
    return dp


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан в .env")
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    init_db()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bot.session.middleware(track_sent_messages)
    dp = create_dispatcher()

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logging.info("Scheduler started")

    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
        await bot.session.close()
        logging.info("Bot stopped gracefully")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
