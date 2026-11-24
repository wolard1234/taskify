from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

from database import db
from web.app import app


class ColumnTemplateTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "test.sqlite"))
        db.init_db()
        self.owner = db.get_or_create_user(101, "owner")["id"]
        self.editor = db.get_or_create_user(102, "editor")["id"]
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.owner

    def test_agile_preserves_tasks_and_reuses_status_columns(self):
        board = db.add_board(self.owner, "Board")["id"]
        todo, doing, done = db.get_columns(board)
        occupied = db.add_column(board, "Waiting")
        db.add_column(board, "Empty")
        kept_ids = [todo["id"], doing["id"], done["id"], occupied["id"]]
        tasks = [db.add_task(self.owner, board, col, f"Task {col}") for col in kept_ids]

        response = self.client.put(f"/api/boards/{board}/column-template", json={"template_id": "agile"})
        self.assertEqual(response.status_code, 200)
        columns = db.get_columns(board)
        self.assertEqual([col["name"] for col in columns], ["Бэклог", "В работе", "На проверке", "Готово", "Waiting"])
        self.assertEqual([col["key"] for col in columns[:4]], ["todo", "in_progress", "review", "done"])
        self.assertEqual([db.get_task(task["id"], self.owner)["column_id"] for task in tasks], kept_ids)
        self.assertEqual(db.get_board_stats(board)["done"], 1)

    def test_custom_template_is_validated_and_available_for_new_boards(self):
        response = self.client.post("/api/column-templates", json={
            "name": "  Процесс  ", "columns": [" Входящие ", "Согласование", "Готово"],
        })
        self.assertEqual(response.status_code, 201)
        template = response.json
        self.assertEqual(template["name"], "Процесс")
        self.assertEqual(self.client.post("/api/column-templates", json={
            "name": "ПРОЦЕСС", "columns": ["Другой этап"],
        }).status_code, 409)
        self.assertEqual(self.client.post("/api/column-templates", json={
            "name": "Дубли", "columns": ["Готово", " готово "],
        }).status_code, 400)

        response = self.client.post("/api/boards", json={"name": "New", "template_id": template["id"]})
        self.assertEqual(response.status_code, 201)
        columns = db.get_columns(response.json["id"])
        self.assertEqual([col["name"] for col in columns], ["Входящие", "Согласование", "Готово"])
        self.assertEqual(columns[-1]["key"], "done")

        with self.client.session_transaction() as session:
            session["user_id"] = self.editor
        response = self.client.post("/api/boards", json={"name": "Other", "template_id": template["id"]})
        self.assertEqual(response.status_code, 404)

    def test_only_owner_can_apply_template_to_existing_board(self):
        board = db.add_board(self.owner, "Shared")["id"]
        before = db.get_columns(board)
        db.add_board_member(board, "editor")
        with self.client.session_transaction() as session:
            session["user_id"] = self.editor
        response = self.client.put(f"/api/boards/{board}/column-template", json={"template_id": "agile"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.get_columns(board), before)


if __name__ == "__main__":
    main()
