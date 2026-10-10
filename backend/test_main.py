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
