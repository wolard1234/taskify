import asyncio, logging, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from database.db import init_db
from bot.handlers import start, tasks
from bot.scheduler import setup_scheduler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в .env")


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp  = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(tasks.router)

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
