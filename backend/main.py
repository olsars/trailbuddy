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
        users.avatar AS owner_avatar
    FROM walks
    JOIN users ON users.id = walks.owner_id
"""


class WalkPointCreate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    recorded_at: datetime | None = None


class WalkSharingUpdate(BaseModel):
    visibility: Literal["private", "friends", "public"]
    allow_follow_race: bool


class FriendRequestCreate(BaseModel):
    recipient_id: str


def user_to_dict(user) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "avatar": user["avatar"],
    }


def walk_to_dict(walk) -> dict:
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

        if point.recorded_at is None:
            recorded_at = datetime.now(timezone.utc)
        else:
            if point.recorded_at.tzinfo is None or point.recorded_at.utcoffset() is None:
                raise HTTPException(
                    status_code=422,
                    detail="recorded_at must include a timezone",
                )
            recorded_at = point.recorded_at.astimezone(timezone.utc)

        recorded_at_value = recorded_at.isoformat()
        cursor = connection.execute(
            """
            INSERT INTO walk_points (walk_id, latitude, longitude, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (walk_id, point.latitude, point.longitude, recorded_at_value),
        )

    return {
        "id": cursor.lastrowid,
        "walk_id": walk_id,
        "latitude": point.latitude,
        "longitude": point.longitude,
        "recorded_at": recorded_at_value,
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
            SELECT id, walk_id, latitude, longitude, recorded_at
            FROM walk_points
            WHERE walk_id = ?
            ORDER BY recorded_at, id
            """,
            (walk_id,),
        ).fetchall()
    return [dict(row) for row in rows]


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


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
