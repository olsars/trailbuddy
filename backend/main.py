import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .database import DEFAULT_DEMO_USER_ID, get_connection, init_db
except ImportError:
    from database import DEFAULT_DEMO_USER_ID, get_connection, init_db

app = FastAPI()
init_db()

WALK_SELECT = """
    SELECT
        walks.id,
        walks.owner_id,
        walks.status,
        walks.start_time,
        walks.end_time,
        walks.visibility,
        walks.allow_follow_race,
        users.display_name AS owner_display_name,
        users.avatar AS owner_avatar,
        walk_summaries.distance_meters AS summary_distance_meters,
        walk_summaries.duration_seconds AS summary_duration_seconds,
        walk_summaries.average_pace_seconds_per_km AS summary_average_pace,
        walk_summaries.point_count AS summary_point_count,
        walk_summaries.computed_at AS summary_computed_at
    FROM walks
    JOIN users ON users.id = walks.owner_id
    LEFT JOIN walk_summaries ON walk_summaries.walk_id = walks.id
"""

EARTH_RADIUS_METERS = 6_371_000
LOCATION_STALE_AFTER_SECONDS = 300

WalkEventType = Literal[
    "check_in_requested",
    "check_in_confirmed",
    "check_in_missed",
    "inactivity_detected",
    "movement_resumed",
    "sos_triggered",
]


class WalkPointCreate(BaseModel):
    client_point_id: str | None = Field(default=None, min_length=1, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    recorded_at: datetime | None = None
    accuracy_meters: float | None = Field(default=None, ge=0)
    altitude_meters: float | None = None
    speed_mps: float | None = Field(default=None, ge=0)


class WalkPointBatchCreate(BaseModel):
    points: list[WalkPointCreate] = Field(min_length=1, max_length=500)


class WalkEventCreate(BaseModel):
    client_event_id: str | None = Field(default=None, min_length=1, max_length=100)
    event_type: WalkEventType
    recorded_at: datetime | None = None
    details: str | None = Field(default=None, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class WalkSharingUpdate(BaseModel):
    visibility: Literal["private", "friends", "public"]
    allow_follow_race: bool


class FriendRequestCreate(BaseModel):
    recipient_id: str


class LocationSharingUpdate(BaseModel):
    enabled: bool


def user_to_dict(user) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "avatar": user["avatar"],
    }


def walk_to_dict(walk) -> dict:
    summary = None
    if walk["summary_computed_at"] is not None:
        summary = {
            "distance_meters": round(walk["summary_distance_meters"], 2),
            "duration_seconds": round(walk["summary_duration_seconds"], 2),
            "average_pace_seconds_per_km": (
                round(walk["summary_average_pace"], 2)
                if walk["summary_average_pace"] is not None
                else None
            ),
            "point_count": walk["summary_point_count"],
            "computed_at": walk["summary_computed_at"],
        }

    return {
        "id": walk["id"],
        "owner_id": walk["owner_id"],
        "owner": {
            "id": walk["owner_id"],
            "display_name": walk["owner_display_name"],
            "avatar": walk["owner_avatar"],
        },
        "status": walk["status"],
        "start_time": walk["start_time"],
        "end_time": walk["end_time"],
        "visibility": walk["visibility"],
        "allow_follow_race": bool(walk["allow_follow_race"]),
        "summary": summary,
    }


def friendship_to_dict(friendship) -> dict:
    requester_id = friendship["requested_by"]
    recipient_id = (
        friendship["user_two_id"]
        if requester_id == friendship["user_one_id"]
        else friendship["user_one_id"]
    )
    return {
        "id": friendship["id"],
        "requester_id": requester_id,
        "recipient_id": recipient_id,
        "status": friendship["status"],
        "created_at": friendship["created_at"],
        "responded_at": friendship["responded_at"],
    }


def get_current_user(
    x_demo_user_id: str = Header(
        default=DEFAULT_DEMO_USER_ID,
        alias="X-Demo-User-Id",
    ),
) -> dict:
    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT id, username, display_name, avatar
            FROM users
            WHERE id = ?
            """,
            (x_demo_user_id,),
        ).fetchone()

    if user is None:
        raise HTTPException(status_code=401, detail="Unknown demo user")
    return user_to_dict(user)


def pair_user_ids(first_user_id: str, second_user_id: str) -> tuple[str, str]:
    return tuple(sorted((first_user_id, second_user_id)))


def users_are_friends(
    connection,
    first_user_id: str,
    second_user_id: str,
) -> bool:
    user_one_id, user_two_id = pair_user_ids(first_user_id, second_user_id)
    friendship = connection.execute(
        """
        SELECT 1
        FROM friendships
        WHERE user_one_id = ? AND user_two_id = ? AND status = 'accepted'
        """,
        (user_one_id, user_two_id),
    ).fetchone()
    return friendship is not None


def can_view_walk(connection, walk, viewer_id: str) -> bool:
    if walk["owner_id"] == viewer_id:
        return True
    if walk["visibility"] == "public":
        return True
    if walk["visibility"] == "friends":
        return users_are_friends(connection, walk["owner_id"], viewer_id)
    return False


def get_walk(connection, walk_id: str):
    return connection.execute(
        f"{WALK_SELECT} WHERE walks.id = ?",
        (walk_id,),
    ).fetchone()


def require_owned_walk(connection, walk_id: str, owner_id: str):
    walk = get_walk(connection, walk_id)
    if walk is None or walk["owner_id"] != owner_id:
        raise HTTPException(status_code=404, detail="Walk not found")
    return walk


def normalize_recorded_at(recorded_at: datetime | None) -> str:
    if recorded_at is None:
        value = datetime.now(timezone.utc)
    else:
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise HTTPException(
                status_code=422,
                detail="recorded_at must include a timezone",
            )
        value = recorded_at.astimezone(timezone.utc)
    return value.isoformat()


def point_to_dict(point) -> dict:
    return {
        "id": point["id"],
        "walk_id": point["walk_id"],
        "client_point_id": point["client_point_id"],
        "latitude": point["latitude"],
        "longitude": point["longitude"],
        "recorded_at": point["recorded_at"],
        "accuracy_meters": point["accuracy_meters"],
        "altitude_meters": point["altitude_meters"],
        "speed_mps": point["speed_mps"],
    }


def update_last_location(
    connection,
    user_id: str,
    walk_id: str,
    point: dict,
) -> None:
    received_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO user_locations (
            user_id,
            walk_id,
            latitude,
            longitude,
            recorded_at,
            received_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            walk_id = excluded.walk_id,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            recorded_at = excluded.recorded_at,
            received_at = excluded.received_at
        WHERE excluded.recorded_at >= user_locations.recorded_at
        """,
        (
            user_id,
            walk_id,
            point["latitude"],
            point["longitude"],
            point["recorded_at"],
            received_at,
        ),
    )


def save_walk_point(
    connection,
    walk,
    point: WalkPointCreate,
) -> tuple[dict, bool]:
    if point.client_point_id is not None:
        existing = connection.execute(
            """
            SELECT *
            FROM walk_points
            WHERE walk_id = ? AND client_point_id = ?
            """,
            (walk["id"], point.client_point_id),
        ).fetchone()
        if existing is not None:
            saved_point = point_to_dict(existing)
            update_last_location(
                connection,
                walk["owner_id"],
                walk["id"],
                saved_point,
            )
            return saved_point, False

    recorded_at = normalize_recorded_at(point.recorded_at)
    cursor = connection.execute(
        """
        INSERT INTO walk_points (
            walk_id,
            client_point_id,
            latitude,
            longitude,
            recorded_at,
            accuracy_meters,
            altitude_meters,
            speed_mps
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            walk["id"],
            point.client_point_id,
            point.latitude,
            point.longitude,
            recorded_at,
            point.accuracy_meters,
            point.altitude_meters,
            point.speed_mps,
        ),
    )
    saved = connection.execute(
        "SELECT * FROM walk_points WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    saved_point = point_to_dict(saved)
    update_last_location(
        connection,
        walk["owner_id"],
        walk["id"],
        saved_point,
    )
    return saved_point, True


def haversine_distance_meters(first, second) -> float:
    first_latitude = math.radians(first["latitude"])
    second_latitude = math.radians(second["latitude"])
    latitude_delta = second_latitude - first_latitude
    longitude_delta = math.radians(second["longitude"] - first["longitude"])
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude)
        * math.cos(second_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    # Floating-point rounding can push this fraction a hair above 1.0 for
    # nearly antipodal coordinates, which would otherwise raise ValueError.
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(min(value, 1.0)))


def refresh_walk_summary(connection, walk_id: str) -> None:
    walk = connection.execute(
        "SELECT start_time, end_time FROM walks WHERE id = ?",
        (walk_id,),
    ).fetchone()
    points = connection.execute(
        """
        SELECT latitude, longitude
        FROM walk_points
        WHERE walk_id = ?
        ORDER BY recorded_at, id
        """,
        (walk_id,),
    ).fetchall()

    distance_meters = sum(
        haversine_distance_meters(first, second)
        for first, second in zip(points, points[1:])
    )
    started_at = datetime.fromisoformat(walk["start_time"])
    ended_at = (
        datetime.fromisoformat(walk["end_time"])
        if walk["end_time"] is not None
        else datetime.now(timezone.utc)
    )
    duration_seconds = max((ended_at - started_at).total_seconds(), 0)
    average_pace = (
        duration_seconds / (distance_meters / 1000)
        if distance_meters > 0
        else None
    )
    computed_at = datetime.now(timezone.utc).isoformat()

    connection.execute(
        """
        INSERT INTO walk_summaries (
            walk_id,
            distance_meters,
            duration_seconds,
            average_pace_seconds_per_km,
            point_count,
            computed_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(walk_id) DO UPDATE SET
            distance_meters = excluded.distance_meters,
            duration_seconds = excluded.duration_seconds,
            average_pace_seconds_per_km = excluded.average_pace_seconds_per_km,
            point_count = excluded.point_count,
            computed_at = excluded.computed_at
        """,
        (
            walk_id,
            distance_meters,
            duration_seconds,
            average_pace,
            len(points),
            computed_at,
        ),
    )


def event_to_dict(event) -> dict:
    return {
        "id": event["id"],
        "walk_id": event["walk_id"],
        "client_event_id": event["client_event_id"],
        "event_type": event["event_type"],
        "recorded_at": event["recorded_at"],
        "details": event["details"],
        "latitude": event["latitude"],
        "longitude": event["longitude"],
    }


def location_to_dict(location) -> dict:
    last_ping_at = location["recorded_at"]
    if last_ping_at is None:
        last_location = None
    else:
        age_seconds = max(
            (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(last_ping_at)
            ).total_seconds(),
            0,
        )
        last_location = {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "last_ping_at": last_ping_at,
            "received_at": location["received_at"],
            "walk_id": location["walk_id"],
            "is_stale": age_seconds > LOCATION_STALE_AFTER_SECONDS,
        }

    return {
        "user": {
            "id": location["user_id"],
            "display_name": location["display_name"],
            "avatar": location["avatar"],
        },
        "last_location": last_location,
    }


def get_user_location(connection, user_id: str):
    return connection.execute(
        """
        SELECT
            users.id AS user_id,
            users.display_name,
            users.avatar,
            user_locations.walk_id,
            user_locations.latitude,
            user_locations.longitude,
            user_locations.recorded_at,
            user_locations.received_at
        FROM users
        LEFT JOIN user_locations ON user_locations.user_id = users.id
        WHERE users.id = ?
        """,
        (user_id,),
    ).fetchone()


@app.get("/")
def home():
    return {"message": "TrailBuddy backend is running!"}


@app.get("/demo/users")
def get_demo_users():
    with get_connection() as connection:
        users = connection.execute(
            """
            SELECT id, username, display_name, avatar
            FROM users
            ORDER BY display_name
            """
        ).fetchall()
    return [user_to_dict(user) for user in users]


@app.get("/demo/me")
def get_demo_me(current_user: dict = Depends(get_current_user)):
    return current_user


@app.get("/walks")
def get_walks(current_user: dict = Depends(get_current_user)):
    with get_connection() as connection:
        rows = connection.execute(
            f"{WALK_SELECT} WHERE walks.owner_id = ? ORDER BY walks.start_time",
            (current_user["id"],),
        ).fetchall()
    return [walk_to_dict(row) for row in rows]


@app.get("/users/{user_id}/walks")
def get_user_walks(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        user_exists = connection.execute(
            "SELECT 1 FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user_exists is None:
            raise HTTPException(status_code=404, detail="User not found")

        walks = connection.execute(
            f"{WALK_SELECT} WHERE walks.owner_id = ? "
            "ORDER BY walks.start_time DESC",
            (user_id,),
        ).fetchall()
        visible_walks = [
            walk_to_dict(walk)
            for walk in walks
            if can_view_walk(connection, walk, current_user["id"])
        ]
    return visible_walks


@app.get("/feed")
def get_walk_feed(current_user: dict = Depends(get_current_user)):
    with get_connection() as connection:
        walks = connection.execute(
            f"{WALK_SELECT} ORDER BY walks.start_time DESC"
        ).fetchall()
        visible_walks = [
            walk_to_dict(walk)
            for walk in walks
            if can_view_walk(connection, walk, current_user["id"])
        ]
    return visible_walks


@app.get("/walks/{walk_id}")
def get_walk_detail(
    walk_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        walk = get_walk(connection, walk_id)
        if walk is None or not can_view_walk(connection, walk, current_user["id"]):
            raise HTTPException(status_code=404, detail="Walk not found")
        if walk["status"] == "completed" and walk["summary_computed_at"] is None:
            refresh_walk_summary(connection, walk_id)
            walk = get_walk(connection, walk_id)
    return walk_to_dict(walk)


@app.post("/walks/start")
def start_walk(current_user: dict = Depends(get_current_user)):
    walk_id = str(uuid4())
    start_time = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO walks (
                id,
                owner_id,
                status,
                start_time,
                end_time,
                visibility,
                allow_follow_race
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                walk_id,
                current_user["id"],
                "active",
                start_time,
                None,
                "private",
                False,
            ),
        )
        walk = get_walk(connection, walk_id)
    return walk_to_dict(walk)


@app.patch("/walks/{walk_id}")
def end_walk(walk_id: str, current_user: dict = Depends(get_current_user)):
    with get_connection() as connection:
        walk = require_owned_walk(connection, walk_id, current_user["id"])
        if walk["status"] == "completed":
            return walk_to_dict(walk)

        end_time = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "UPDATE walks SET status = ?, end_time = ? WHERE id = ?",
            ("completed", end_time, walk_id),
        )
        refresh_walk_summary(connection, walk_id)
        ended_walk = get_walk(connection, walk_id)
    return walk_to_dict(ended_walk)


@app.patch("/walks/{walk_id}/sharing")
def update_walk_sharing(
    walk_id: str,
    sharing: WalkSharingUpdate,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        require_owned_walk(connection, walk_id, current_user["id"])
        connection.execute(
            """
            UPDATE walks
            SET visibility = ?, allow_follow_race = ?
            WHERE id = ?
            """,
            (sharing.visibility, sharing.allow_follow_race, walk_id),
        )
        walk = get_walk(connection, walk_id)
    return walk_to_dict(walk)


@app.post("/walks/{walk_id}/points")
def add_walk_point(
    walk_id: str,
    point: WalkPointCreate,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        walk = require_owned_walk(connection, walk_id, current_user["id"])
        if walk["status"] != "active":
            raise HTTPException(status_code=409, detail="Walk is not active")
        saved_point, _ = save_walk_point(connection, walk, point)
    return saved_point


@app.post("/walks/{walk_id}/points/batch")
def add_walk_points_batch(
    walk_id: str,
    batch: WalkPointBatchCreate,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        walk = require_owned_walk(connection, walk_id, current_user["id"])
        if walk["status"] != "active":
            raise HTTPException(status_code=409, detail="Walk is not active")

        saved_points = []
        created_count = 0
        for point in batch.points:
            saved_point, created = save_walk_point(connection, walk, point)
            saved_points.append(saved_point)
            created_count += int(created)

    return {
        "created_count": created_count,
        "duplicate_count": len(saved_points) - created_count,
        "points": saved_points,
    }


@app.get("/walks/{walk_id}/points")
def get_walk_points(
    walk_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        walk = get_walk(connection, walk_id)
        if walk is None or not can_view_walk(connection, walk, current_user["id"]):
            raise HTTPException(status_code=404, detail="Walk not found")

        rows = connection.execute(
            """
            SELECT
                id,
                walk_id,
                client_point_id,
                latitude,
                longitude,
                recorded_at,
                accuracy_meters,
                altitude_meters,
                speed_mps
            FROM walk_points
            WHERE walk_id = ?
            ORDER BY recorded_at, id
            """,
            (walk_id,),
        ).fetchall()
    return [point_to_dict(row) for row in rows]


@app.post("/walks/{walk_id}/events")
def add_walk_event(
    walk_id: str,
    event: WalkEventCreate,
    current_user: dict = Depends(get_current_user),
):
    if (event.latitude is None) != (event.longitude is None):
        raise HTTPException(
            status_code=422,
            detail="latitude and longitude must be provided together",
        )

    with get_connection() as connection:
        walk = require_owned_walk(connection, walk_id, current_user["id"])
        if walk["status"] != "active":
            raise HTTPException(status_code=409, detail="Walk is not active")

        if event.client_event_id is not None:
            existing = connection.execute(
                """
                SELECT *
                FROM walk_events
                WHERE walk_id = ? AND client_event_id = ?
                """,
                (walk_id, event.client_event_id),
            ).fetchone()
            if existing is not None:
                return event_to_dict(existing)

        event_id = str(uuid4())
        recorded_at = normalize_recorded_at(event.recorded_at)
        connection.execute(
            """
            INSERT INTO walk_events (
                id,
                walk_id,
                client_event_id,
                event_type,
                recorded_at,
                details,
                latitude,
                longitude
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                walk_id,
                event.client_event_id,
                event.event_type,
                recorded_at,
                event.details,
                event.latitude,
                event.longitude,
            ),
        )
        saved_event = connection.execute(
            "SELECT * FROM walk_events WHERE id = ?",
            (event_id,),
        ).fetchone()
    return event_to_dict(saved_event)


@app.get("/walks/{walk_id}/events")
def get_walk_events(
    walk_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        require_owned_walk(connection, walk_id, current_user["id"])
        events = connection.execute(
            """
            SELECT *
            FROM walk_events
            WHERE walk_id = ?
            ORDER BY recorded_at, id
            """,
            (walk_id,),
        ).fetchall()
    return [event_to_dict(event) for event in events]


@app.get("/friends")
def get_friends(current_user: dict = Depends(get_current_user)):
    with get_connection() as connection:
        friendships = connection.execute(
            """
            SELECT user_one_id, user_two_id
            FROM friendships
            WHERE status = 'accepted'
              AND (user_one_id = ? OR user_two_id = ?)
            ORDER BY created_at
            """,
            (current_user["id"], current_user["id"]),
        ).fetchall()

        friend_ids = [
            row["user_two_id"]
            if row["user_one_id"] == current_user["id"]
            else row["user_one_id"]
            for row in friendships
        ]
        friends = []
        for friend_id in friend_ids:
            friend = connection.execute(
                """
                SELECT id, username, display_name, avatar
                FROM users
                WHERE id = ?
                """,
                (friend_id,),
            ).fetchone()
            friends.append(user_to_dict(friend))
    return friends


@app.get("/friend-requests")
def get_friend_requests(current_user: dict = Depends(get_current_user)):
    with get_connection() as connection:
        requests = connection.execute(
            """
            SELECT *
            FROM friendships
            WHERE status = 'pending'
              AND (user_one_id = ? OR user_two_id = ?)
            ORDER BY created_at
            """,
            (current_user["id"], current_user["id"]),
        ).fetchall()
    return [friendship_to_dict(request) for request in requests]


@app.post("/friend-requests")
def send_friend_request(
    request: FriendRequestCreate,
    current_user: dict = Depends(get_current_user),
):
    if request.recipient_id == current_user["id"]:
        raise HTTPException(
            status_code=400,
            detail="You cannot send a friend request to yourself",
        )

    user_one_id, user_two_id = pair_user_ids(
        current_user["id"], request.recipient_id
    )
    with get_connection() as connection:
        recipient = connection.execute(
            "SELECT id FROM users WHERE id = ?",
            (request.recipient_id,),
        ).fetchone()
        if recipient is None:
            raise HTTPException(status_code=404, detail="Demo user not found")

        existing = connection.execute(
            """
            SELECT id
            FROM friendships
            WHERE user_one_id = ? AND user_two_id = ?
            """,
            (user_one_id, user_two_id),
        ).fetchone()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="A friendship or friend request already exists",
            )

        request_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO friendships (
                id,
                user_one_id,
                user_two_id,
                requested_by,
                status,
                created_at,
                responded_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?, NULL)
            """,
            (
                request_id,
                user_one_id,
                user_two_id,
                current_user["id"],
                created_at,
            ),
        )
        friend_request = connection.execute(
            "SELECT * FROM friendships WHERE id = ?",
            (request_id,),
        ).fetchone()
    return friendship_to_dict(friend_request)


@app.patch("/friend-requests/{request_id}/accept")
def accept_friend_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        friend_request = connection.execute(
            "SELECT * FROM friendships WHERE id = ?",
            (request_id,),
        ).fetchone()
        if friend_request is None:
            raise HTTPException(status_code=404, detail="Friend request not found")

        serialized_request = friendship_to_dict(friend_request)
        if serialized_request["recipient_id"] != current_user["id"]:
            raise HTTPException(
                status_code=403,
                detail="Only the recipient can accept this friend request",
            )
        if friend_request["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail="Friend request is not pending",
            )

        responded_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            UPDATE friendships
            SET status = 'accepted', responded_at = ?
            WHERE id = ?
            """,
            (responded_at, request_id),
        )
        accepted_request = connection.execute(
            "SELECT * FROM friendships WHERE id = ?",
            (request_id,),
        ).fetchone()
    return friendship_to_dict(accepted_request)


@app.get("/location-sharing")
def get_location_sharing(current_user: dict = Depends(get_current_user)):
    with get_connection() as connection:
        friendships = connection.execute(
            """
            SELECT user_one_id, user_two_id
            FROM friendships
            WHERE status = 'accepted'
              AND (user_one_id = ? OR user_two_id = ?)
            ORDER BY created_at
            """,
            (current_user["id"], current_user["id"]),
        ).fetchall()

        settings = []
        for friendship in friendships:
            friend_id = (
                friendship["user_two_id"]
                if friendship["user_one_id"] == current_user["id"]
                else friendship["user_one_id"]
            )
            friend = connection.execute(
                """
                SELECT id, username, display_name, avatar
                FROM users
                WHERE id = ?
                """,
                (friend_id,),
            ).fetchone()
            share = connection.execute(
                """
                SELECT enabled, updated_at
                FROM location_shares
                WHERE owner_id = ? AND viewer_id = ?
                """,
                (current_user["id"], friend_id),
            ).fetchone()
            settings.append(
                {
                    "friend": user_to_dict(friend),
                    "enabled": bool(share["enabled"]) if share is not None else False,
                    "updated_at": share["updated_at"] if share is not None else None,
                }
            )
    return settings


@app.patch("/location-sharing/{friend_id}")
def update_location_sharing(
    friend_id: str,
    sharing: LocationSharingUpdate,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        if not users_are_friends(connection, current_user["id"], friend_id):
            raise HTTPException(
                status_code=403,
                detail="Location can only be shared with an accepted friend",
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO location_shares (
                owner_id,
                viewer_id,
                enabled,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, viewer_id) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                current_user["id"],
                friend_id,
                sharing.enabled,
                timestamp,
                timestamp,
            ),
        )
        friend = connection.execute(
            """
            SELECT id, username, display_name, avatar
            FROM users
            WHERE id = ?
            """,
            (friend_id,),
        ).fetchone()
    return {
        "friend": user_to_dict(friend),
        "enabled": sharing.enabled,
        "updated_at": timestamp,
    }


@app.get("/locations/shared-with-me")
def get_locations_shared_with_me(
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        shares = connection.execute(
            """
            SELECT owner_id
            FROM location_shares
            WHERE viewer_id = ? AND enabled = 1
            ORDER BY updated_at DESC
            """,
            (current_user["id"],),
        ).fetchall()
        locations = [
            location_to_dict(get_user_location(connection, share["owner_id"]))
            for share in shares
            if users_are_friends(
                connection,
                share["owner_id"],
                current_user["id"],
            )
        ]
    return locations


@app.get("/locations/{user_id}")
def get_shared_location(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        location = get_user_location(connection, user_id)
        if location is None:
            raise HTTPException(status_code=404, detail="Location not found")

        if user_id != current_user["id"]:
            share = connection.execute(
                """
                SELECT enabled
                FROM location_shares
                WHERE owner_id = ? AND viewer_id = ?
                """,
                (user_id, current_user["id"]),
            ).fetchone()
            if (
                share is None
                or not share["enabled"]
                or not users_are_friends(connection, user_id, current_user["id"])
            ):
                raise HTTPException(status_code=404, detail="Location not found")
    return location_to_dict(location)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
