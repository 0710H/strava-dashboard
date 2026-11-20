import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import app as app_module


class ActivityCrudTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.users = [{"user_id": 3, "username": "demo_runner"}]
        self.routes = [
            {
                "route_id": 8,
                "route_name": "Park loop",
                "user_id": 4,
                "username": "another_runner",
            }
        ]
        self.activity_data = {
            "title": "Morning run",
            "description": "Steady effort",
            "distance": "12.34",
            "activity_date": "2026-11-18T07:30",
            "duration": "2700",
            "route_id": "8",
        }
        self.activity = {
            "activity_id": 17,
            "user_id": 3,
            "route_id": 8,
            "title": "Morning run",
            "description": "Steady effort",
            "distance": Decimal("12.34"),
            "activity_date": datetime(2026, 11, 18, 7, 30),
            "duration": 2700,
        }
        self.current_user = {
            "user_id": 3,
            "username": "demo_runner",
            "email": "demo@example.test",
        }

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 3
            sess["username"] = "demo_runner"

    def test_create_requires_login(self):
        response = self.client.post("/activities/new", data=self.activity_data)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_create_activity_uses_logged_in_user(self):
        self._login()
        with (
            patch.object(app_module, "get_current_user", return_value=self.current_user),
            patch.object(
                app_module,
                "fetch_one",
                side_effect=[{"route_id": 8}],
            ),
            patch.object(app_module, "execute_write") as execute_write,
        ):
            response = self.client.post("/activities/new", data=self.activity_data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/activities?notice=created")
        query, parameters = execute_write.call_args.args
        self.assertIn("INSERT INTO activities", query)
        self.assertEqual(
            parameters,
            (
                3,
                8,
                "Morning run",
                "Steady effort",
                Decimal("12.34"),
                datetime(2026, 11, 18, 7, 30),
                2700,
            ),
        )

    def test_create_rejects_nonexistent_route(self):
        self._login()
        with (
            patch.object(app_module, "get_current_user", return_value=self.current_user),
            patch.object(app_module, "fetch_one", return_value=None),
            patch.object(app_module, "fetch_all", return_value=self.routes),
            patch.object(app_module, "execute_write") as execute_write,
        ):
            response = self.client.post("/activities/new", data=self.activity_data)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Choose an existing route.", response.data)
        execute_write.assert_not_called()

    def test_create_renders_validation_errors_without_writing(self):
        self._login()
        invalid_data = dict(self.activity_data, title=" ", distance="-1")
        with (
            patch.object(app_module, "get_current_user", return_value=self.current_user),
            patch.object(app_module, "fetch_all", return_value=self.routes),
            patch.object(app_module, "execute_write") as execute_write,
        ):
            response = self.client.post("/activities/new", data=invalid_data)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter an activity title.", response.data)
        self.assertIn(b"Enter a valid distance greater than zero.", response.data)
        execute_write.assert_not_called()

    def test_edit_activity_updates_existing_record(self):
        self._login()
        updated_data = dict(self.activity_data, title="Updated run")
        with (
            patch.object(app_module, "get_current_user", return_value=self.current_user),
            patch.object(
                app_module,
                "fetch_one",
                side_effect=[self.activity, {"route_id": 8}],
            ),
            patch.object(app_module, "execute_write") as execute_write,
        ):
            response = self.client.post("/activities/17/edit", data=updated_data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/activities?notice=updated")
        query, parameters = execute_write.call_args.args
        self.assertIn("UPDATE activities", query)
        self.assertEqual(parameters[-2], 17)
        self.assertEqual(parameters[-1], 3)
        self.assertEqual(parameters[1], "Updated run")

    def test_edit_forbidden_for_other_users_activity(self):
        self._login()
        other_activity = dict(self.activity, user_id=99)
        with (
            patch.object(app_module, "get_current_user", return_value=self.current_user),
            patch.object(app_module, "fetch_one", return_value=other_activity),
        ):
            response = self.client.post("/activities/17/edit", data=self.activity_data)

        self.assertEqual(response.status_code, 403)

    def test_delete_confirmation_explains_cascade(self):
        self._login()
        activity = {
            "activity_id": 17,
            "user_id": 3,
            "title": "Morning run",
            "username": "demo_runner",
            "kudos_count": 2,
            "comment_count": 1,
        }
        with (
            patch.object(app_module, "get_current_user", return_value=self.current_user),
            patch.object(app_module, "fetch_one", return_value=activity),
        ):
            response = self.client.get("/activities/17/delete")

        html = b" ".join(response.data.split())
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"2 kudos", html)
        self.assertIn(b"1 comment", html)
        self.assertIn(b"Delete activity and related data", html)

    def test_delete_post_removes_activity_and_redirects(self):
        self._login()
        with (
            patch.object(app_module, "get_current_user", return_value=self.current_user),
            patch.object(app_module, "fetch_one", return_value=self.activity),
            patch.object(app_module, "execute_write") as execute_write,
        ):
            response = self.client.post("/activities/17/delete")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/activities?notice=deleted")
        query, parameters = execute_write.call_args.args
        self.assertIn("DELETE FROM activities", query)
        self.assertEqual(parameters, (17, 3))

    def test_activity_feed_remains_readable_and_offers_login_or_create(self):
        with patch.object(app_module, "fetch_all", return_value=[]):
            response = self.client.get("/activities")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"All activities", response.data)
        self.assertIn(b"Log in to add", response.data)


if __name__ == "__main__":
    unittest.main()
