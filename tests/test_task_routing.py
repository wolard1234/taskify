from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch

from database import db
from web.app import app


class TaskRoutingTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.object(db, "DB_PATH", Path(directory) / "routing.sqlite"))
        db.init_db()
        self.users = {name: db.get_or_create_user(tg, name)["id"] for tg, name in enumerate(
            ("owner", "sender", "guest", "lead", "worker", "observer", "outsider"), start=100
        )}
        self.source = db.add_board(self.users["owner"], "Analytics")["id"]
        self.target = db.add_board(self.users["owner"], "CX")["id"]
        for board, members in ((self.source, ("sender", "guest")), (self.target, ("lead", "worker", "observer"))):
            for member in members:
                db.add_board_member(board, member)
        db.update_department(self.source, self.users["owner"], self.users["owner"], {self.users["sender"]})
        db.update_department(self.target, self.users["owner"], self.users["lead"], {self.users["worker"]})
        self.client = app.test_client()
        self.sign_in("sender")
        self.notify = self.enterContext(patch("web.app.notify_telegram"))

    def sign_in(self, name):
        with self.client.session_transaction() as session:
            session["user_id"] = self.users[name]

    def test_department_goes_to_lead_and_lead_can_delegate(self):
        response = self.client.post("/api/tasks", json={
            "title": "Delegate this", "board_id": self.source, "department_id": self.target,
        })
        self.assertEqual(response.status_code, 201)
        task = response.json
        self.assertEqual((task["board_id"], task["column_id"], task["assignee_id"]), (
            self.target, db.get_columns(self.target)[0]["id"], self.users["lead"],
        ))
        self.assertFalse(task["can_open_board"])
        self.assertEqual(self.client.get(f"/api/boards/{self.target}/columns").status_code, 404)
        self.assertIn("От @sender", self.notify.call_args.args[1])

        self.sign_in("lead")
        response = self.client.patch(f"/api/tasks/{task['id']}", json={"assignee_id": self.users["worker"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn("От @lead", self.notify.call_args.args[1])
        self.assertEqual([t["id"] for t in db.get_all_tasks_for_user(self.users["worker"])], [task["id"]])
        self.assertEqual(db.get_all_tasks_for_user(self.users["lead"]), [])

    def test_direct_and_self_assignments_start_in_todo(self):
        target_column_ids = [col["id"] for col in db.get_columns(self.target)]
        db.reorder_columns(self.target, self.users["owner"], target_column_ids, target_column_ids[::-1])
        direct = self.client.post("/api/tasks", json={
            "title": "Direct", "board_id": self.source, "department_id": self.target, "assignee_id": self.users["worker"],
        })
        self.assertEqual(direct.status_code, 201)
        self.assertEqual(direct.json["assignee_id"], self.users["worker"])
        self.assertEqual(direct.json["column_id"], target_column_ids[0])

        own = self.client.post("/api/tasks", json={"title": "Mine", "board_id": self.source, "assignee_id": self.users["sender"]})
        self.assertEqual(own.status_code, 201)
        self.assertEqual(own.json["assignee_id"], self.users["sender"])
        self.assertEqual(own.json["column_id"], db.get_columns(self.source)[0]["id"])
        self.assertEqual(self.notify.call_count, 1)

    def test_department_permissions(self):
        foreign = db.add_board(self.users["outsider"], "Other org")["id"]
        db.update_department(foreign, self.users["outsider"], self.users["outsider"], set())
        for department, recipient in ((self.target, self.users["observer"]), (foreign, None)):
            response = self.client.post("/api/tasks", json={
                "title": "Rejected", "board_id": self.source, "department_id": department, "assignee_id": recipient,
            })
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.put(f"/api/boards/{self.source}/department", json={
            "lead_id": self.users["sender"], "staff_ids": [],
        }).status_code, 403)

        for user, expected in (("sender", True), ("guest", False)):
            self.sign_in(user)
            page = self.client.get(f"/?board_id={self.source}").get_data(as_text=True)
            departments = page.split('id="f-department"', 1)[1].split("</select>", 1)[0]
            self.assertEqual(f'value="{self.target}"' in departments, expected)
        self.assertEqual(self.client.post("/api/tasks", json={
            "title": "Guest route", "board_id": self.source, "department_id": self.target,
        }).status_code, 400)
        self.notify.assert_not_called()

    def test_removing_lead_disables_route(self):
        self.sign_in("owner")
        self.assertEqual(self.client.delete(f"/api/boards/{self.target}/members/{self.users['lead']}").status_code, 200)
        self.assertEqual(self.client.post("/api/tasks", json={
            "title": "Missing lead", "board_id": self.source, "department_id": self.target,
        }).status_code, 400)
        self.notify.assert_not_called()


if __name__ == "__main__":
    main()
