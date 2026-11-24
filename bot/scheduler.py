"""
Notifications scheduler for Taskify bot.
- Daily digest at 09:00 (configured via DIGEST_HOUR env var)
- Deadline reminders: checks every 30 min, notifies 24h before deadline
"""
import asyncio
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from html import escape

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.navigation import back_to_menu_kb
from database.db import get_upcoming_deadlines, get_all_active_tasks_for_digest

logger = logging.getLogger(__name__)

PRIO_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}

# track already notified task deadlines to avoid duplicate alerts
_notified_deadlines: set[tuple[int, int, str]] = set()


def _fmt_dl(iso: str | None) -> str:
    """'YYYY-MM-DD HH:MM' → 'DD.MM.YYYY HH:MM'"""
    if not iso:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}))?", iso)
    if not m:
        return iso
    y, mo, d, t = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"{d}.{mo}.{y} {t}" if t else f"{d}.{mo}.{y}"


async def send_deadline_reminders(bot: Bot):
    """Sends reminders for tasks with deadlines within 24 hours."""
    try:
        tasks = get_upcoming_deadlines(hours=24)
        # group by user
        by_user: dict[int, list] = defaultdict(list)
        for t in tasks:
            if t["telegram_id"] and (t["id"], t["telegram_id"], t["deadline"]) not in _notified_deadlines:
                by_user[t["telegram_id"]].append(t)

        for tg_id, user_tasks in by_user.items():
            lines = ["⏰ <b>Напоминание о дедлайнах:</b>\n"]
            for t in user_tasks:
                prio = PRIO_EMOJI.get(t.get("priority", "medium"), "")
                lines.append(f"{prio} <b>{escape(t['title'])}</b>\n   📅 {_fmt_dl(t['deadline'])}")
            try:
                await bot.send_message(tg_id, "\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_kb())
                _notified_deadlines.update((t["id"], tg_id, t["deadline"]) for t in user_tasks)
            except Exception as e:
                logger.warning(f"Failed to send deadline reminder to {tg_id}: {e}")
    except Exception as e:
        logger.error(f"Deadline reminder error: {e}")


async def send_daily_digest(bot: Bot):
    """Sends daily digest of active tasks to all users at configured hour."""
    try:
        tasks = get_all_active_tasks_for_digest()
        if not tasks:
            return

        by_user: dict[int, list] = defaultdict(list)
        for t in tasks:
            if t["telegram_id"]:
                by_user[t["telegram_id"]].append(t)

        bot_username = (os.getenv("BOT_USERNAME") or "taskifyjobs_bot").lstrip("@")
        for tg_id, user_tasks in by_user.items():
            total = len(user_tasks)
            high  = sum(1 for t in user_tasks if t.get("priority") == "high")
            overdue = [
                t for t in user_tasks
                if t.get("deadline") and t["deadline"] < datetime.now().strftime("%Y-%m-%d %H:%M")
            ]

            lines = [
                f"☀️ <b>Доброе утро! Дайджест задач на сегодня:</b>\n",
                f"Активных задач: <b>{total}</b>",
            ]
            if high:
                lines.append(f"Высокий приоритет: <b>{high}</b> 🔴")
            if overdue:
                lines.append(f"Просроченных: <b>{len(overdue)}</b> ⚠️")

            # top 5 high priority
            top = sorted(user_tasks, key=lambda t: (
                {"high": 0, "medium": 1, "low": 2}.get(t.get("priority", "medium"), 1),
                t.get("deadline") or "9999",
            ))[:5]

            if top:
                lines.append("\n<b>Приоритетные задачи:</b>")
                for t in top:
                    prio = PRIO_EMOJI.get(t.get("priority", "medium"), "")
                    dl = f" 📅 {_fmt_dl(t['deadline'])}" if t.get("deadline") else ""
                    lines.append(f"{prio} {escape(t['title'])}{dl}")

            lines.append(f"\nОткрой @{bot_username}, чтобы управлять задачами.")

            try:
                await bot.send_message(tg_id, "\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_kb())
            except Exception as e:
                logger.warning(f"Failed to send digest to {tg_id}: {e}")
    except Exception as e:
        logger.error(f"Daily digest error: {e}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    digest_hour = int(os.getenv("DIGEST_HOUR", "9"))

    # Daily digest
    scheduler.add_job(
        send_daily_digest,
        trigger="cron",
        hour=digest_hour,
        minute=0,
        args=[bot],
        id="daily_digest",
    )

    # Deadline reminders every 30 minutes
    scheduler.add_job(
        send_deadline_reminders,
        trigger="interval",
        minutes=30,
        args=[bot],
        id="deadline_reminders",
    )

    return scheduler
