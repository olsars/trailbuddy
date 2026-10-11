# TrailBuddy

Project made for KnightHacks IX!

A Raspberry Pi hiking companion featuring a pixel-art animal companion, GPS tracking, 
and friend location sharing.

## Technologies Used
The backend is implemented with Python, and the frontend is implemented with CSS, HTML, and JavaScript. Frameworks and tools we used include FastAPI, Leaflet, React-Leaflet, and Vite. The
physical platform is a Raspberry Pi with a 128×64 display. OpenStreetMap is also used.


## Quick demo

```powershell
python -m pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)   # the backend serves frontend/dist at /app/
python -m uvicorn backend.main:app --host 0.0.0.0 --reload
```

Open `http://127.0.0.1:8000/app/`, start a walk, then either use the page's demo
GPS button or run `python gps/simulator.py --walk-id YOUR_WALK_ID` in another
terminal. The trail and walk history are stored locally in SQLite.

The backend also seeds Sam, Xavian, Pablo, and Laeh as demo profiles. It supports
friend requests, private/friends/public walk visibility, a separate follow/race
permission, and a visibility-filtered walk feed without requiring signup. It
also stores safety check-in events, accepts retry-safe offline GPS batches,
calculates walk summaries, and supports opt-in friend location sharing with a
Last Ping timestamp.

## How to Run and Access the Application (Frontend)
```powershell
npm --prefix frontend run dev
```

Open `http://localhost:5178/` to view the web application.

## Assumptions and Limitations: 
This web application is run on a local server.