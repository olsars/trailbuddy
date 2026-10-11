import os, sqlite3, requests
from datetime import datetime, timezone

BASE = os.environ.get("TRAILBUDDY_API", "http://192.168.135.93:8000")
HEADERS = {"X-Demo-User-Id": "pablo"}

db = sqlite3.connect(os.path.expanduser("~/trailbuddy.db"))

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()

wid = db.execute("SELECT MAX(id) FROM walks").fetchone()[0]
rows = db.execute("SELECT ts, lat, lon FROM points WHERE walk_id=? ORDER BY ts", (wid,)).fetchall()
points = [{"client_point_id": f"{wid}-{ts}", "latitude": lat, "longitude": lon,
           "recorded_at": iso(ts)} for ts, lat, lon in rows]
print(len(points), "points to send")

r = requests.post(f"{BASE}/walks/start", headers=HEADERS, timeout=10)
print("start:", r.status_code, r.text[:300])
r.raise_for_status()
server_id = r.json()["id"]

for i in range(0, len(points), 500):
    r = requests.post(f"{BASE}/walks/{server_id}/points/batch", headers=HEADERS,
                      json={"points": points[i:i + 500]}, timeout=20)
    print("points:", r.status_code, r.text[:200])
    r.raise_for_status()

r = requests.patch(f"{BASE}/walks/{server_id}", headers=HEADERS, timeout=10)
print("end:", r.status_code, r.text[:300])
