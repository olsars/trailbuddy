import os, sqlite3, requests

SERVER_URL = "http://192.168.135.93:8000/docs"   # your teammate's endpoint

db = sqlite3.connect(os.path.expanduser("~/trailbuddy.db"))

def build_payload(wid):
    w = db.execute("SELECT start_ts, end_ts, distance_m FROM walks WHERE id=?", (wid,)).fetchone()
    pts = db.execute("SELECT ts, lat, lon FROM points WHERE walk_id=? ORDER BY ts", (wid,)).fetchall()
    return {"walk_id": wid, "start_ts": w[0], "end_ts": w[1], "distance_m": w[2],
            "points": [{"ts": t, "lat": la, "lon": lo} for t, la, lo in pts]}

latest = db.execute("SELECT MAX(id) FROM walks").fetchone()[0]

import json
p = build_payload(latest)
print(json.dumps(p)[:300])          # the start of what would be sent
print(len(p["points"]), "points")

r = requests.post(SERVER_URL, json=build_payload(latest), timeout=10)
print(r.status_code, r.text[:200])