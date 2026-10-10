import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "trailbuddy.db"
DEFAULT_DEMO_USER_ID = "sam"

DEMO_USERS = (
    ("sam", "sam", "Sam", "cat"),
    ("xavian", "xavian", "Xavian", "capybara"),
    ("pablo", "pablo", "Pablo", "dog"),
    ("laeh", "laeh", "Laeh", "bear"),
)

LEGACY_DEMO_USER_MIGRATIONS = (
    ("jordan", "Jordan", "bear", "xavian"),
    ("maya", "Maya", "frog", "pablo"),
)


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


def _add_missing_walk_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(walks)").fetchall()
    }

    # SQLite cannot add a non-null foreign-key column to a populated table, so
    # owner_id is added as nullable for existing databases and backfilled below.
    if "owner_id" not in columns:
        connection.execute(
            "ALTER TABLE walks ADD COLUMN owner_id TEXT REFERENCES users (id)"
        )
    if "visibility" not in columns:
        connection.execute(
            "ALTER TABLE walks ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'"
        )
    if "allow_follow_race" not in columns:
        connection.execute(
            "ALTER TABLE walks ADD COLUMN allow_follow_race INTEGER NOT NULL DEFAULT 0"
        )

    connection.execute(
        "UPDATE walks SET owner_id = ? WHERE owner_id IS NULL",
        (DEFAULT_DEMO_USER_ID,),
    )


def _add_missing_walk_point_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(walk_points)").fetchall()
    }

    if "client_point_id" not in columns:
        connection.execute("ALTER TABLE walk_points ADD COLUMN client_point_id TEXT")
    if "accuracy_meters" not in columns:
        connection.execute("ALTER TABLE walk_points ADD COLUMN accuracy_meters REAL")
    if "altitude_meters" not in columns:
        connection.execute("ALTER TABLE walk_points ADD COLUMN altitude_meters REAL")
    if "speed_mps" not in columns:
        connection.execute("ALTER TABLE walk_points ADD COLUMN speed_mps REAL")


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                avatar TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        created_at = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            """
            INSERT INTO users (
                id, username, display_name, avatar, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name,
                avatar = excluded.avatar
            """,
            [(*user, created_at) for user in DEMO_USERS],
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS walks (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'sam',
                status TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                visibility TEXT NOT NULL DEFAULT 'private'
                    CHECK (visibility IN ('private', 'friends', 'public')),
                allow_follow_race INTEGER NOT NULL DEFAULT 0
                    CHECK (allow_follow_race IN (0, 1)),
                FOREIGN KEY (owner_id) REFERENCES users (id)
            )
            """
        )
        _add_missing_walk_columns(connection)

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS walk_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                walk_id TEXT NOT NULL,
                client_point_id TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                accuracy_meters REAL,
                altitude_meters REAL,
                speed_mps REAL,
                FOREIGN KEY (walk_id) REFERENCES walks (id) ON DELETE CASCADE
            )
            """
        )
        _add_missing_walk_point_columns(connection)
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_walk_points_walk_time
            ON walk_points (walk_id, recorded_at, id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_walk_points_client_id
            ON walk_points (walk_id, client_point_id)
            WHERE client_point_id IS NOT NULL
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS friendships (
                id TEXT PRIMARY KEY,
                user_one_id TEXT NOT NULL,
                user_two_id TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN ('pending', 'accepted', 'declined')),
                created_at TEXT NOT NULL,
                responded_at TEXT,
                CHECK (user_one_id < user_two_id),
                CHECK (requested_by IN (user_one_id, user_two_id)),
                UNIQUE (user_one_id, user_two_id),
                FOREIGN KEY (user_one_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (user_two_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (requested_by) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_friendships_status
            ON friendships (status, user_one_id, user_two_id)
            """
        )

        # Seed one accepted friendship and one pending request so the social
        # flow can be demonstrated without account creation.
        connection.executemany(
            """
            INSERT OR IGNORE INTO friendships (
                id,
                user_one_id,
                user_two_id,
                requested_by,
                status,
                created_at,
                responded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "demo-sam-xavian",
                    "sam",
                    "xavian",
                    "sam",
                    "accepted",
                    created_at,
                    created_at,
                ),
                (
                    "demo-pablo-sam",
                    "pablo",
                    "sam",
                    "pablo",
                    "pending",
                    created_at,
                    None,
                ),
            ),
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS walk_events (
                id TEXT PRIMARY KEY,
                walk_id TEXT NOT NULL,
                client_event_id TEXT,
                event_type TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                details TEXT,
                latitude REAL,
                longitude REAL,
                FOREIGN KEY (walk_id) REFERENCES walks (id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_walk_events_walk_id
            ON walk_events (walk_id, recorded_at, id)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_walk_events_client_id
            ON walk_events (walk_id, client_event_id)
            WHERE client_event_id IS NOT NULL
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS walk_summaries (
                walk_id TEXT PRIMARY KEY,
                distance_meters REAL NOT NULL,
                duration_seconds REAL NOT NULL,
                average_pace_seconds_per_km REAL,
                point_count INTEGER NOT NULL,
                computed_at TEXT NOT NULL,
                FOREIGN KEY (walk_id) REFERENCES walks (id) ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS location_shares (
                owner_id TEXT NOT NULL,
                viewer_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (owner_id, viewer_id),
                CHECK (owner_id != viewer_id),
                FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (viewer_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_location_shares_viewer
            ON location_shares (viewer_id, enabled)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_locations (
                user_id TEXT PRIMARY KEY,
                walk_id TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (walk_id) REFERENCES walks (id) ON DELETE SET NULL
            )
            """
        )

        # Preserve legacy walk history while replacing the original placeholder
        # demo profiles. Social and last-location data is intentionally reset so
        # the new seeded relationships remain predictable for the demo.
        for (
            legacy_user_id,
            legacy_display_name,
            legacy_avatar,
            replacement_user_id,
        ) in LEGACY_DEMO_USER_MIGRATIONS:
            legacy_user = connection.execute(
                """
                SELECT 1
                FROM users
                WHERE id = ?
                  AND username = ?
                  AND display_name = ?
                  AND avatar = ?
                """,
                (
                    legacy_user_id,
                    legacy_user_id,
                    legacy_display_name,
                    legacy_avatar,
                ),
            ).fetchone()
            if legacy_user is None:
                continue

            connection.execute(
                "UPDATE walks SET owner_id = ? WHERE owner_id = ?",
                (replacement_user_id, legacy_user_id),
            )
            connection.execute(
                """
                DELETE FROM friendships
                WHERE user_one_id = ? OR user_two_id = ? OR requested_by = ?
                """,
                (legacy_user_id, legacy_user_id, legacy_user_id),
            )
            connection.execute(
                "DELETE FROM location_shares WHERE owner_id = ? OR viewer_id = ?",
                (legacy_user_id, legacy_user_id),
            )
            connection.execute(
                "DELETE FROM user_locations WHERE user_id = ?",
                (legacy_user_id,),
            )
            connection.execute(
                "DELETE FROM users WHERE id = ?",
                (legacy_user_id,),
            )
