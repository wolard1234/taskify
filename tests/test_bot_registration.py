import json
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase, main
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import Chat, Message, Update

from bot.navigation import track_sent_messages
from database import db
from run_bot import create_dispatcher
from web import app as web


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
    @classmethod
    def setUpClass(cls):
        cls.dispatcher = create_dispatcher()

    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "bot.sqlite"))
        db.init_db()
        self.bot = Bot(token="12345:test")
        self.bot.session.middleware(track_sent_messages)
        self.addAsyncCleanup(self.bot.session.close)
        self.update_id = 1
        self.message_id = 0

        async def request(bot, method, timeout=None):
            if isinstance(method, SendMessage):
                self.message_id += 1
                return Message(
                    message_id=self.message_id, date=datetime.now(timezone.utc),
                    chat=Chat(id=method.chat_id, type="private"), text=method.text,
                )
            return True

        self.request = self.enterContext(patch.object(self.bot.session, "make_request", AsyncMock(side_effect=request)))

    async def feed(self, telegram_id, *, text=None, callback=None, chat_type="private", message_id=None):
        user = {"id": telegram_id, "is_bot": False, "first_name": "Тест", "username": f"tester{telegram_id}"}
        if message_id is None:
            self.message_id += 1
            message_id = self.message_id
        message = {
            "message_id": message_id, "date": 1795432800, "from": user,
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
        self.enterContext(patch.dict("os.environ", {"ADMIN_TELEGRAM_IDS": " 103 "}))
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

        response, = await self.feed(101, text="/list")
        self.assertIn("Тебе не назначено активных задач", response.text)
        db.add_board_member(cx, "tester101")
        todo, _, done = db.get_columns(cx)
        db.add_task(owner, cx, todo["id"], "Назначена мне", assignee_id=employee)
        db.add_task(owner, cx, done["id"], "Выполнена мной", assignee_id=employee)
        db.add_task(employee, cx, todo["id"], "Назначил другому", assignee_id=lead)
        for response in ((await self.feed(101, callback="menu:list"))[0], (await self.feed(101, text="/list"))[0]):
            self.assertIn("Назначена мне", response.text)
            for excluded in ("Первая задача", "Выполнена мной", "Назначил другому"):
                self.assertNotIn(excluded, response.text)
        responses = await self.feed(101, callback="menu:all")
        self.assertIn("Первая задача", responses[0].text)

        responses = await self.feed(102, callback="menu:departments")
        self.assertIn("CX", responses[0].text)
        self.assertNotIn("Методология", responses[0].text)
        responses = await self.feed(103, callback="menu:departments")
        self.assertIn("CX", responses[0].text)
        self.assertIn("Методология", responses[0].text)
        db.update_department(cx, owner, owner, set())
        response, = await self.feed(102, callback="menu:departments")
        self.assertTrue(response.show_alert)

    async def test_navigation_edits_current_message_and_sends_for_older_buttons(self):
        telegram_id = 201
        user = db.get_or_create_user(telegram_id, "tester201")["id"]
        board = db.add_board(user, "CX")["id"]
        db.update_department(board, user, user, set())
        db.register_user(user, board, "Иванов Иван")
        todo = db.get_columns(board)[0]
        task = db.add_task(user, board, todo["id"], "Задача")

        await self.feed(telegram_id, text="/start")
        menu_id = self.message_id
        card, _ = await self.feed(telegram_id, callback=f"task:view:{task['id']}", message_id=menu_id)
        self.assertIsInstance(card, EditMessageText)
        self.assertEqual(card.message_id, menu_id)
        self.assertEqual(card.reply_markup.inline_keyboard[-1][0].callback_data, "menu:main")

        menu, _ = await self.feed(telegram_id, callback="menu:main", message_id=menu_id)
        self.assertIsInstance(menu, EditMessageText)
        self.assertEqual(menu.message_id, menu_id)

        await self.feed(telegram_id, text="Обычное сообщение")
        menu, _ = await self.feed(telegram_id, callback="menu:main", message_id=menu_id)
        self.assertIsInstance(menu, SendMessage)
        new_menu_id = self.message_id

        profile, _ = await self.feed(telegram_id, callback="menu:profile", message_id=new_menu_id)
        self.assertIsInstance(profile, EditMessageText)
        self.assertEqual(profile.message_id, new_menu_id)

        self.message_id += 1
        notification_id = self.message_id
        result = BytesIO(json.dumps({"result": {"message_id": notification_id}}).encode())
        result.status = 200
        with patch.object(web, "BOT_TOKEN", "test"), patch.object(web, "urlopen", return_value=result) as send:
            web.notify_task_assignee({**task, "assignee_id": user}, {"id": user + 1, "username": "owner"})
        rows = json.loads(send.call_args.args[0].data)["reply_markup"]["inline_keyboard"]
        self.assertEqual([row[0]["callback_data"] for row in rows], [f"task:view:{task['id']}", "menu:main"])

        db.record_telegram_message(telegram_id, new_menu_id)
        card, _ = await self.feed(telegram_id, callback=f"task:view:{task['id']}", message_id=notification_id)
        self.assertIsInstance(card, EditMessageText)
        self.assertEqual(card.message_id, notification_id)
        profile, _ = await self.feed(telegram_id, callback="menu:profile", message_id=new_menu_id)
        self.assertIsInstance(profile, SendMessage)

        prompt, _ = await self.feed(telegram_id, callback="menu:add", message_id=self.message_id)
        self.assertIsInstance(prompt, EditMessageText)
        await self.feed(telegram_id, text="Новая задача")
        wizard_id = self.message_id
        deadline, _ = await self.feed(telegram_id, callback="prio:medium", message_id=wizard_id)
        self.assertIsInstance(deadline, EditMessageText)
        confirmation, _ = await self.feed(telegram_id, callback="dl:skip", message_id=wizard_id)
        self.assertIsInstance(confirmation, EditMessageText)
        self.assertIn("Новая задача", confirmation.text)

    async def test_task_buttons_follow_the_current_order_of_its_board(self):
        telegram_id = 301
        owner = db.get_or_create_user(300, "owner")["id"]
        employee = db.get_or_create_user(telegram_id, "tester301")["id"]
        profile_board = db.add_board(owner, "CX")["id"]
        task_board = db.add_board(owner, "Аналитики", columns=["Бэклог", "В работе", "На проверке", "Готово"])["id"]
        db.update_department(profile_board, owner, owner, set())
        db.register_user(employee, profile_board, "Иванов Иван")
        db.add_board_member(task_board, "tester301")
        backlog, working, review, done = [column["id"] for column in db.get_columns(task_board)]
        task_id = db.add_task(owner, task_board, working, "Анализ", assignee_id=employee)["id"]

        card, _ = await self.feed(telegram_id, callback=f"task:view:{task_id}")
        buttons = card.reply_markup.inline_keyboard
        self.assertEqual([row[0].text for row in buttons], ["На проверке", "Готово", "◀️ Назад", "◀️ Главное меню"])
        review_button, done_button = [row[0].callback_data for row in buttons[:2]]

        foreign = db.get_columns(profile_board)[-1]["id"]
        for callback in (f"task:move:{task_id}:{foreign}", f"task:done:{task_id}"):
            card, _ = await self.feed(telegram_id, callback=callback)
            self.assertIn("📂 В работе", card.text)

        db.update_column(review, task_board, name="Согласование")
        self.assertTrue(db.reorder_columns(task_board, owner, [backlog, working, review, done], [backlog, review, working, done]))
        card, _ = await self.feed(telegram_id, callback=review_button)
        self.assertEqual(db.get_task(task_id, employee)["column_id"], working)
        self.assertEqual([row[0].text for row in card.reply_markup.inline_keyboard], ["Готово", "◀️ Назад", "◀️ Главное меню"])

        self.assertTrue(db.reorder_columns(task_board, owner, [backlog, review, working, done], [backlog, working, done, review]))
        card, answer = await self.feed(telegram_id, callback=done_button)
        self.assertIn("📂 Готово", card.text)
        self.assertIn("Задача перемещена", answer.text)
        next_button = card.reply_markup.inline_keyboard[0][0]
        self.assertEqual(next_button.text, "Согласование")
        card, _ = await self.feed(telegram_id, callback=next_button.callback_data)
        self.assertEqual(db.get_task(task_id, employee)["column_id"], review)
        self.assertEqual([row[0].callback_data for row in card.reply_markup.inline_keyboard], ["menu:list", "menu:main"])


if __name__ == "__main__":
    main()
