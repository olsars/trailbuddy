import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "trailbuddy.db"


def get_database_path() -> Path:
    configured_path = os.getenv("TRAILBUDDY_DB_PATH")
    return Path(configured_path).expanduser().resolve() if configured_path else DEFAULT_DB_PATH


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    db_path = get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS walks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS walk_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                walk_id TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (walk_id) REFERENCES walks (id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_walk_points_walk_id
            ON walk_points (walk_id, id)
            """
        )
