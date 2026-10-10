# TrailBuddy

Project made for KnightHacks IX!

A privacy-first Raspberry Pi hiking companion featuring
pixel-art animal companions, GPS tracking, smart check-ins,
emergency contacts, and optional friend location sharing.

## Quick demo

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000/app/`, start a walk, then either use the page's demo
GPS button or run `python gps/simulator.py --walk-id YOUR_WALK_ID` in another
terminal. The trail and walk history are stored locally in SQLite.

The backend also seeds Sam, Jordan, and Maya as demo profiles. It supports
friend requests, private/friends/public walk visibility, a separate follow/race
permission, and a visibility-filtered walk feed without requiring signup.
