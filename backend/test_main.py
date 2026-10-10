import importlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class WalkApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "trailbuddy-test.db"
        os.environ["TRAILBUDDY_DB_PATH"] = str(self.db_path)

        import backend.main

        self.main = importlib.reload(backend.main)
        self.client = TestClient(self.main.app)

    def tearDown(self) -> None:
        self.client.close()
        os.environ.pop("TRAILBUDDY_DB_PATH", None)
        self.temp_dir.cleanup()

    @staticmethod
    def headers_for(user_id: str) -> dict[str, str]:
        return {"X-Demo-User-Id": user_id}

    def test_start_list_end_and_persist_after_restart(self) -> None:
        self.assertEqual(
            self.client.get("/").json(),
            {"message": "TrailBuddy backend is running!"},
        )

        start_response = self.client.post("/walks/start")
        self.assertEqual(start_response.status_code, 200)
        started_walk = start_response.json()
        self.assertEqual(started_walk["status"], "active")
        self.assertIsNone(started_walk["end_time"])

        list_response = self.client.get("/walks")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json(), [started_walk])

        first_point_response = self.client.post(
            f"/walks/{started_walk['id']}/points",
            json={"latitude": 40.7128, "longitude": -74.0060},
        )
        self.assertEqual(first_point_response.status_code, 200)
        first_point = first_point_response.json()
        self.assertEqual(first_point["walk_id"], started_walk["id"])
        self.assertEqual(first_point["latitude"], 40.7128)

        second_point_response = self.client.post(
            f"/walks/{started_walk['id']}/points",
            json={"latitude": 40.7132, "longitude": -74.0055},
        )
        self.assertEqual(second_point_response.status_code, 200)
        second_point = second_point_response.json()

        points_response = self.client.get(f"/walks/{started_walk['id']}/points")
        self.assertEqual(points_response.status_code, 200)
        self.assertEqual(points_response.json(), [first_point, second_point])

        end_response = self.client.patch(f"/walks/{started_walk['id']}")
        self.assertEqual(end_response.status_code, 200)
        ended_walk = end_response.json()
        self.assertEqual(ended_walk["status"], "completed")
        self.assertIsNotNone(ended_walk["end_time"])

        inactive_response = self.client.post(
            f"/walks/{started_walk['id']}/points",
            json={"latitude": 40.7135, "longitude": -74.0050},
        )
        self.assertEqual(inactive_response.status_code, 409)

        restarted_main = importlib.reload(self.main)
        with TestClient(restarted_main.app) as restarted_client:
            self.assertEqual(restarted_client.get("/walks").json(), [ended_walk])
            self.assertEqual(
                restarted_client.get(f"/walks/{started_walk['id']}/points").json(),
                [first_point, second_point],
            )

    def test_ending_unknown_walk_returns_404(self) -> None:
        response = self.client.patch("/walks/does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Walk not found"})

        points_response = self.client.get("/walks/does-not-exist/points")
        self.assertEqual(points_response.status_code, 404)

    def test_invalid_point_is_rejected(self) -> None:
        walk_id = self.client.post("/walks/start").json()["id"]

        response = self.client.post(
            f"/walks/{walk_id}/points",
            json={"latitude": 100, "longitude": -74},
        )

        self.assertEqual(response.status_code, 422)

    def test_demo_users_and_seeded_friendships(self) -> None:
        users_response = self.client.get("/demo/users")

        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(
            {user["id"] for user in users_response.json()},
            {"sam", "jordan", "maya"},
        )
        self.assertEqual(
            self.client.get("/demo/me").json()["id"],
            "sam",
        )
        self.assertEqual(
            [friend["id"] for friend in self.client.get("/friends").json()],
            ["jordan"],
        )

        requests = self.client.get("/friend-requests").json()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["requester_id"], "maya")
        self.assertEqual(requests[0]["recipient_id"], "sam")

        unknown_user_response = self.client.get(
            "/demo/me",
            headers=self.headers_for("does-not-exist"),
        )
        self.assertEqual(unknown_user_response.status_code, 401)

    def test_friend_request_can_be_sent_and_accepted(self) -> None:
        sent_response = self.client.post(
            "/friend-requests",
            headers=self.headers_for("jordan"),
            json={"recipient_id": "maya"},
        )

        self.assertEqual(sent_response.status_code, 200)
        friend_request = sent_response.json()
        self.assertEqual(friend_request["status"], "pending")
        self.assertEqual(friend_request["requester_id"], "jordan")
        self.assertEqual(friend_request["recipient_id"], "maya")

        wrong_user_response = self.client.patch(
            f"/friend-requests/{friend_request['id']}/accept",
            headers=self.headers_for("sam"),
        )
        self.assertEqual(wrong_user_response.status_code, 403)

        accepted_response = self.client.patch(
            f"/friend-requests/{friend_request['id']}/accept",
            headers=self.headers_for("maya"),
        )
        self.assertEqual(accepted_response.status_code, 200)
        self.assertEqual(accepted_response.json()["status"], "accepted")

        jordan_friends = self.client.get(
            "/friends",
            headers=self.headers_for("jordan"),
        ).json()
        self.assertEqual(
            {friend["id"] for friend in jordan_friends},
            {"sam", "maya"},
        )

    def test_walk_visibility_and_timed_points(self) -> None:
        jordan_headers = self.headers_for("jordan")
        started_walk = self.client.post(
            "/walks/start",
            headers=jordan_headers,
        ).json()
        self.assertEqual(started_walk["owner_id"], "jordan")
        self.assertEqual(started_walk["visibility"], "private")
        self.assertFalse(started_walk["allow_follow_race"])

        recorded_at = "2026-10-10T12:34:56-04:00"
        point_response = self.client.post(
            f"/walks/{started_walk['id']}/points",
            headers=jordan_headers,
            json={
                "latitude": 28.6024,
                "longitude": -81.2001,
                "recorded_at": recorded_at,
            },
        )
        self.assertEqual(point_response.status_code, 200)
        self.assertEqual(
            point_response.json()["recorded_at"],
            "2026-10-10T16:34:56+00:00",
        )

        private_feed = self.client.get("/feed").json()
        self.assertNotIn(started_walk["id"], {walk["id"] for walk in private_feed})

        sharing_response = self.client.patch(
            f"/walks/{started_walk['id']}/sharing",
            headers=jordan_headers,
            json={"visibility": "friends", "allow_follow_race": True},
        )
        self.assertEqual(sharing_response.status_code, 200)
        self.assertEqual(sharing_response.json()["visibility"], "friends")
        self.assertTrue(sharing_response.json()["allow_follow_race"])

        sam_feed = self.client.get("/feed").json()
        self.assertIn(started_walk["id"], {walk["id"] for walk in sam_feed})

        maya_feed = self.client.get(
            "/feed",
            headers=self.headers_for("maya"),
        ).json()
        self.assertNotIn(started_walk["id"], {walk["id"] for walk in maya_feed})

        sam_points_response = self.client.get(
            f"/walks/{started_walk['id']}/points"
        )
        self.assertEqual(sam_points_response.status_code, 200)
        self.assertEqual(len(sam_points_response.json()), 1)

        maya_points_response = self.client.get(
            f"/walks/{started_walk['id']}/points",
            headers=self.headers_for("maya"),
        )
        self.assertEqual(maya_points_response.status_code, 404)

        non_owner_response = self.client.patch(
            f"/walks/{started_walk['id']}/sharing",
            json={"visibility": "public", "allow_follow_race": True},
        )
        self.assertEqual(non_owner_response.status_code, 404)

    def test_batch_points_events_and_walk_summary(self) -> None:
        walk = self.client.post("/walks/start").json()
        walk_id = walk["id"]

        batch_response = self.client.post(
            f"/walks/{walk_id}/points/batch",
            json={
                "points": [
                    {
                        "client_point_id": "gps-1",
                        "latitude": 28.6024,
                        "longitude": -81.2001,
                        "recorded_at": "2026-10-10T12:00:00-04:00",
                        "accuracy_meters": 3.5,
                        "altitude_meters": 20.0,
                        "speed_mps": 1.2,
                    },
                    {
                        "client_point_id": "gps-2",
                        "latitude": 28.6034,
                        "longitude": -81.2001,
                        "recorded_at": "2026-10-10T12:01:00-04:00",
                    },
                    {
                        "client_point_id": "gps-2",
                        "latitude": 28.6034,
                        "longitude": -81.2001,
                        "recorded_at": "2026-10-10T12:01:00-04:00",
                    },
                ]
            },
        )

        self.assertEqual(batch_response.status_code, 200)
        batch = batch_response.json()
        self.assertEqual(batch["created_count"], 2)
        self.assertEqual(batch["duplicate_count"], 1)
        self.assertEqual(len(self.client.get(f"/walks/{walk_id}/points").json()), 2)

        duplicate_response = self.client.post(
            f"/walks/{walk_id}/points/batch",
            json={
                "points": [
                    {
                        "client_point_id": "gps-1",
                        "latitude": 0,
                        "longitude": 0,
                        "recorded_at": "2026-10-10T13:00:00-04:00",
                    }
                ]
            },
        )
        self.assertEqual(duplicate_response.json()["created_count"], 0)
        self.assertEqual(duplicate_response.json()["duplicate_count"], 1)

        event_payload = {
            "client_event_id": "check-in-1",
            "event_type": "check_in_requested",
            "recorded_at": "2026-10-10T12:00:30-04:00",
            "details": "Scheduled safety check-in",
            "latitude": 28.6024,
            "longitude": -81.2001,
        }
        first_event = self.client.post(
            f"/walks/{walk_id}/events",
            json=event_payload,
        ).json()
        duplicate_event = self.client.post(
            f"/walks/{walk_id}/events",
            json=event_payload,
        ).json()
        self.assertEqual(first_event, duplicate_event)
        self.assertEqual(
            self.client.get(f"/walks/{walk_id}/events").json(),
            [first_event],
        )

        ended_walk = self.client.patch(f"/walks/{walk_id}").json()
        summary = ended_walk["summary"]
        self.assertIsNotNone(summary)
        self.assertEqual(summary["point_count"], 2)
        self.assertGreater(summary["distance_meters"], 100)
        self.assertIsNotNone(summary["average_pace_seconds_per_km"])

        detail_response = self.client.get(f"/walks/{walk_id}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["summary"], summary)

        completed_event_response = self.client.post(
            f"/walks/{walk_id}/events",
            json={"event_type": "check_in_confirmed"},
        )
        self.assertEqual(completed_event_response.status_code, 409)

    def test_friend_location_sharing_and_last_ping(self) -> None:
        walk_id = self.client.post("/walks/start").json()["id"]
        point = self.client.post(
            f"/walks/{walk_id}/points",
            json={"latitude": 28.6024, "longitude": -81.2001},
        ).json()

        jordan_headers = self.headers_for("jordan")
        hidden_response = self.client.get(
            "/locations/sam",
            headers=jordan_headers,
        )
        self.assertEqual(hidden_response.status_code, 404)

        enabled_response = self.client.patch(
            "/location-sharing/jordan",
            json={"enabled": True},
        )
        self.assertEqual(enabled_response.status_code, 200)
        self.assertTrue(enabled_response.json()["enabled"])

        shared_response = self.client.get(
            "/locations/shared-with-me",
            headers=jordan_headers,
        )
        self.assertEqual(shared_response.status_code, 200)
        shared_locations = shared_response.json()
        self.assertEqual(len(shared_locations), 1)
        self.assertEqual(shared_locations[0]["user"]["id"], "sam")
        self.assertEqual(
            shared_locations[0]["last_location"]["last_ping_at"],
            point["recorded_at"],
        )
        self.assertFalse(shared_locations[0]["last_location"]["is_stale"])

        pending_friend_response = self.client.patch(
            "/location-sharing/sam",
            headers=self.headers_for("maya"),
            json={"enabled": True},
        )
        self.assertEqual(pending_friend_response.status_code, 403)

        disabled_response = self.client.patch(
            "/location-sharing/jordan",
            json={"enabled": False},
        )
        self.assertEqual(disabled_response.status_code, 200)
        self.assertFalse(disabled_response.json()["enabled"])
        self.assertEqual(
            self.client.get(
                "/locations/shared-with-me",
                headers=jordan_headers,
            ).json(),
            [],
        )

        settings = self.client.get("/location-sharing").json()
        jordan_setting = next(
            setting for setting in settings if setting["friend"]["id"] == "jordan"
        )
        self.assertFalse(jordan_setting["enabled"])

    def test_walk_event_coordinates_must_be_a_pair(self) -> None:
        walk_id = self.client.post("/walks/start").json()["id"]

        response = self.client.post(
            f"/walks/{walk_id}/events",
            json={
                "event_type": "inactivity_detected",
                "latitude": 28.6024,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_legacy_walk_database_is_migrated(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                """
                CREATE TABLE walks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO walks (id, status, start_time, end_time)
                VALUES ('legacy-walk', 'completed', '2026-01-01T00:00:00+00:00', NULL)
                """
            )
            connection.execute(
                """
                CREATE TABLE walk_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    walk_id TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        os.environ["TRAILBUDDY_DB_PATH"] = str(legacy_path)
        from backend.database import init_db

        init_db()

        connection = sqlite3.connect(legacy_path)
        try:
            connection.row_factory = sqlite3.Row
            migrated_walk = connection.execute(
                """
                SELECT owner_id, visibility, allow_follow_race
                FROM walks
                WHERE id = 'legacy-walk'
                """
            ).fetchone()
            point_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(walk_points)"
                ).fetchall()
            }
        finally:
            connection.close()

        self.assertEqual(migrated_walk["owner_id"], "sam")
        self.assertEqual(migrated_walk["visibility"], "private")
        self.assertEqual(migrated_walk["allow_follow_race"], 0)
        self.assertTrue(
            {
                "client_point_id",
                "accuracy_meters",
                "altitude_meters",
                "speed_mps",
            }.issubset(point_columns)
        )

    def test_trail_dashboard_is_served(self) -> None:
        response = self.client.get("/app/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("TrailBuddy", response.text)

    def test_database_connection_is_closed_after_use(self) -> None:
        from backend.database import get_connection

        with get_connection() as connection:
            connection.execute("SELECT 1")

        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_default_database_path_is_stable(self) -> None:
        from backend.database import DEFAULT_DB_PATH, get_database_path

        configured_path = os.environ.pop("TRAILBUDDY_DB_PATH")
        try:
            self.assertEqual(get_database_path(), DEFAULT_DB_PATH)
            self.assertEqual(DEFAULT_DB_PATH.parent, Path(__file__).resolve().parent)
        finally:
            os.environ["TRAILBUDDY_DB_PATH"] = configured_path


if __name__ == "__main__":
    unittest.main()
