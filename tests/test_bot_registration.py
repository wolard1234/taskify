from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase, main
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.types import Update

from database import db
from run_bot import create_dispatcher


class RegistrationMigrationTests(TestCase):
    def test_legacy_user_keeps_tasks_and_completes_profile(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "legacy.sqlite"))
        with closing(db.get_connection()) as conn, conn:
            conn.executescript("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE, username TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO users (id, telegram_id, username) VALUES (9, 109, 'legacy');
            """)
        db.init_db()
        user = db.get_or_create_user(109, "legacy")
        self.assertEqual((user["id"], user["full_name"], user["department_id"]), (9, "", None))
        personal = db.add_board(user["id"], "Personal")["id"]
        task = db.add_task(user["id"], personal, None, "Keep this task")
        owner = db.get_or_create_user(110, "owner")["id"]
        department = db.add_board(owner, "CX")["id"]
        self.assertFalse(db.register_user(user["id"], department, "Иванов Иван"))
        db.update_department(department, owner, owner, set())
        self.assertTrue(db.register_user(user["id"], department, "Иванов Иван"))
        self.assertFalse(db.register_user(user["id"], department, "Другая Фамилия"))
        self.assertEqual(db.get_user_by_id(user["id"])["full_name"], "Иванов Иван")
        self.assertEqual(db.get_task(task["id"], user["id"])["title"], "Keep this task")
        self.assertFalse(db.user_can_edit_board(department, user["id"]))


class RegistrationBotTests(IsolatedAsyncioTestCase):
    async def feed(self, telegram_id, *, text=None, callback=None, chat_type="private"):
        user = {"id": telegram_id, "is_bot": False, "first_name": "Тест", "username": f"tester{telegram_id}"}
        message = {
            "message_id": self.update_id, "date": 1795432800, "from": user,
            "chat": {"id": telegram_id if chat_type == "private" else -100, "type": chat_type},
            "text": text if callback is None else "Меню",
        }
        payload = {"message": message} if callback is None else {"callback_query": {
            "id": str(self.update_id), "from": user, "chat_instance": "test", "data": callback, "message": message,
        }}
        before = self.request.await_count
        await self.dispatcher.feed_update(self.bot, Update.model_validate({"update_id": self.update_id, **payload}))
        self.update_id += 1
        return [call.args[1] for call in self.request.await_args_list[before:]]

    async def test_registration_gates_commands_callbacks_and_role_scopes(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "bot.sqlite"))
        self.enterContext(patch.dict("os.environ", {"ADMIN_TELEGRAM_IDS": " 103 "}))
        db.init_db()
        owner = db.get_or_create_user(100, "owner")["id"]
        employee = db.get_or_create_user(101, "tester101")["id"]
        lead = db.get_or_create_user(102, "tester102")["id"]
        admin = db.get_or_create_user(103, "tester103")["id"]
        cx = db.add_board(owner, "CX")["id"]
        method = db.add_board(owner, "Методология")["id"]
        hidden = db.add_board(owner, "Не отдел")["id"]
        db.add_board_member(cx, "tester102")
        db.update_department(cx, owner, lead, set())
        db.update_department(method, owner, owner, set())
        db.register_user(lead, cx, "Петров Пётр")
        db.register_user(admin, cx, "Сидоров Сидор")

        self.dispatcher = create_dispatcher()
        self.bot = Bot(token="12345:test")
        self.addAsyncCleanup(self.bot.session.close)
        self.request = self.enterContext(patch.object(self.bot.session, "make_request", AsyncMock(return_value=True)))
        self.update_id = 1

        self.assertEqual(await self.feed(101, text="/start", chat_type="group"), [])
        for text in ("/start", "/add Нельзя создать задачу"):
            response, = await self.feed(101, text=text)
            self.assertEqual([row[0].callback_data for row in response.reply_markup.inline_keyboard], [
                f"reg:department:{cx}", f"reg:department:{method}",
            ])
        self.assertEqual(db.get_all_tasks_for_user(employee), [])
        responses = await self.feed(101, callback=f"reg:department:{hidden}")
        self.assertIn("выбери доступный отдел", responses[0].text)
        responses = await self.feed(101, callback=f"reg:department:{cx}")
        self.assertIn("отчество", responses[-1].text)
        response, = await self.feed(101, callback="menu:web")
        self.assertTrue(response.show_alert)
        response, = await self.feed(101, text="123")
        self.assertIn("фамилию и имя", response.text)
        self.assertIsNone(db.get_user_by_id(employee)["department_id"])
        response, = await self.feed(101, text="  Иванов  Иван Иванович ")
        self.assertIn("Иванов Иван Иванович", response.text)
        keys = [button.callback_data for row in response.reply_markup.inline_keyboard for button in row]
        self.assertIn("menu:profile", keys)
        self.assertIn("menu:add", keys)
        self.assertNotIn("menu:departments", keys)
        self.assertEqual(db.get_user_by_id(employee)["department_id"], cx)
        self.assertFalse(db.user_can_edit_board(cx, employee))

        responses = await self.feed(101, callback="menu:profile")
        self.assertIn("Роль: Сотрудник", responses[0].text)
        response, = await self.feed(101, callback="menu:departments")
        self.assertTrue(response.show_alert)
        response, = await self.feed(101, text="/add Первая задача")
        self.assertIn("Задача добавлена", response.text)

        responses = await self.feed(102, callback="menu:departments")
        self.assertIn("CX", responses[0].text)
        self.assertNotIn("Методология", responses[0].text)
        responses = await self.feed(103, callback="menu:departments")
        self.assertIn("CX", responses[0].text)
        self.assertIn("Методология", responses[0].text)
        db.update_department(cx, owner, owner, set())
        response, = await self.feed(102, callback="menu:departments")
        self.assertTrue(response.show_alert)


if __name__ == "__main__":
    main()
