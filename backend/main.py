from fastapi import FastAPI, HTTPException
from uuid import uuid4
from datetime import datetime, timezone

app = FastAPI()
walks = {}

@app.get("/")
def home():
    return {"message": "TrailBuddy backend is running!"}

@app.get("/walks")
def get_walks():
    return walks

@app.post("/walks/start")
def start_walk():
    walk_id = str(uuid4())
    walk = {
        "id": walk_id,
        "status": "active",
        "start_time": datetime.now(timezone.dst).isoformat(),
        "end_time": 0
    }
    walks[walk_id] = walk
    return walk

@app.patch("/walks/{walk_id}")
def end_walk(walk_id: str):
    if walk_id not in walks:
        raise HTTPException(status_code=404, detail="Walk not found")
    walk = walks[walk_id]
    walk["status"] = "completed"
    walk["end_time"] = datetime.now(timezone.dst).isoformat()
    return walk
