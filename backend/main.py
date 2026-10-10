from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .database import get_connection, init_db
except ImportError:
    from database import get_connection, init_db

app = FastAPI()
init_db()


class WalkPointCreate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@app.get("/")
def home():
    return {"message": "TrailBuddy backend is running!"}


@app.get("/walks")
def get_walks():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, status, start_time, end_time FROM walks ORDER BY start_time"
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/walks/start")
def start_walk():
    walk_id = str(uuid4())
    walk = {
        "id": walk_id,
        "status": "active",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": None,
    }
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO walks (id, status, start_time, end_time)
            VALUES (?, ?, ?, ?)
            """,
            (walk["id"], walk["status"], walk["start_time"], walk["end_time"]),
        )
    return walk


@app.patch("/walks/{walk_id}")
def end_walk(walk_id: str):
    with get_connection() as connection:
        walk = connection.execute(
            "SELECT id, status, start_time, end_time FROM walks WHERE id = ?",
            (walk_id,),
        ).fetchone()
        if walk is None:
            raise HTTPException(status_code=404, detail="Walk not found")

        end_time = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "UPDATE walks SET status = ?, end_time = ? WHERE id = ?",
            ("completed", end_time, walk_id),
        )

    return {
        "id": walk["id"],
        "status": "completed",
        "start_time": walk["start_time"],
        "end_time": end_time,
    }


@app.post("/walks/{walk_id}/points")
def add_walk_point(walk_id: str, point: WalkPointCreate):
    with get_connection() as connection:
        walk = connection.execute(
            "SELECT status FROM walks WHERE id = ?",
            (walk_id,),
        ).fetchone()
        if walk is None:
            raise HTTPException(status_code=404, detail="Walk not found")
        if walk["status"] != "active":
            raise HTTPException(status_code=409, detail="Walk is not active")

        recorded_at = datetime.now(timezone.utc).isoformat()
        cursor = connection.execute(
            """
            INSERT INTO walk_points (walk_id, latitude, longitude, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (walk_id, point.latitude, point.longitude, recorded_at),
        )

    return {
        "id": cursor.lastrowid,
        "walk_id": walk_id,
        "latitude": point.latitude,
        "longitude": point.longitude,
        "recorded_at": recorded_at,
    }


@app.get("/walks/{walk_id}/points")
def get_walk_points(walk_id: str):
    with get_connection() as connection:
        walk = connection.execute(
            "SELECT id FROM walks WHERE id = ?",
            (walk_id,),
        ).fetchone()
        if walk is None:
            raise HTTPException(status_code=404, detail="Walk not found")

        rows = connection.execute(
            """
            SELECT id, walk_id, latitude, longitude, recorded_at
            FROM walk_points
            WHERE walk_id = ?
            ORDER BY id
            """,
            (walk_id,),
        ).fetchall()
    return [dict(row) for row in rows]


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
