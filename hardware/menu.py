import math
import os
import sqlite3
import threading
import time
import traceback
from datetime import datetime, timezone
from signal import pause

import pynmea2
import requests
import serial
from gpiozero import Button
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import Image

# ---------- config (override with environment variables) ----------
BASE = os.environ.get("TRAILBUDDY_API", "http://192.168.135.93:8000").rstrip("/")
USER = os.environ.get("TRAILBUDDY_USER", "pablo")
VISIBILITY = os.environ.get("TRAILBUDDY_VISIBILITY", "private")   # private | friends | public
GPS_PORT = os.environ.get("TRAILBUDDY_GPS_PORT", "/dev/ttyAMA0")
DB_PATH = os.path.expanduser(os.environ.get("TRAILBUDDY_DB", "~/trailbuddy.db"))
HERE = os.path.dirname(os.path.abspath(__file__))
DECAY_SECONDS = 30      # seconds between pet stat decay ticks
UPLOAD_SECONDS = 2      # how often the live uploader checks for new points
HAPPY_PER_METER = 0.10  # walking: +1 happiness per 10 m
HUNGER_PER_METER = 0.05 # walking: +1 hunger per 20 m

try:
    # ---------- sprites ----------
    def sprite_path(name):
        for folder in (os.path.join(HERE, "image"), HERE):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return path
        raise FileNotFoundError(f"{name} not found in {HERE}/image or {HERE}")

    def load_sprite(name, cells=(34, 36)):
        img = Image.open(sprite_path(name)).convert("L")
        img = img.resize(cells, Image.NEAREST)          # one pixel per art cell
        img = img.point(lambda p: 255 if p > 128 else 0)
        return img.convert("1")

    frames = {
        "idle":  load_sprite("cat-eyes.png"),
        "blink": load_sprite("cat.png"),
        "happy": load_sprite("cat-smile.png"),
    }
    for name, f in frames.items():
        print(name, f.size, f.histogram()[255], "white pixels")

    seq = ["idle"] * 5 + ["blink"] + ["idle"] * 3 + ["blink", "idle"]
    tick = 0
    cat = frames["idle"]
    bounce = 0

    # ---------- hardware ----------
    lock = threading.Lock()
    device = ssd1306(i2c(port=1, address=0x3C))
    btn = Button(17, hold_time=0.8)
    held = False

    # ---------- state ----------
    menus = {
        "main": ["Buddy", "Start Walk"],
        "pet":  ["Feed", "Pet", "Back"],
    }
    state = "main"          # main | pet | ready | walk | end
    cursor = 0
    hunger = 50             # 0 = full, 100 = starving
    happy = 50              # 0 = sad, 100 = happy
    react_until = 0

    walk_id = None          # local id of the walk in progress
    walk_t0 = 0.0           # time.monotonic() at start (immune to the Pi's clock being corrected)
    walk_secs = 0
    distance_m = 0.0
    last_pos = None
    gps = {"fix": False}
    net = {"ok": False, "open": 0, "pending": 0}   # live-upload status, kept up to date by the uploader
    wake = threading.Event()                       # wakes the uploader right away (walk start / end)

    # ---------- local database (also the offline queue) ----------
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db_lock = threading.Lock()

    def init_db():
        with db_lock:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS walks (id INTEGER PRIMARY KEY, start_ts REAL, end_ts REAL, distance_m REAL);
            CREATE TABLE IF NOT EXISTS points (walk_id INTEGER, ts REAL, lat REAL, lon REAL);
            """)

            def add_column(table, column, ddl, backfill=None):
                existing = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    if backfill:
                        db.execute(backfill)

            add_column("walks", "server_id", "TEXT")
            # walks and points from before live uploading were handled by the old Send flow: don't re-upload them
            add_column("walks", "synced", "INTEGER NOT NULL DEFAULT 0", "UPDATE walks SET synced = 1")
            add_column("points", "sent", "INTEGER NOT NULL DEFAULT 0", "UPDATE points SET sent = 1")
            add_column("points", "speed", "REAL")
            db.commit()

    def recover_unfinished():
        """A walk still open after a power loss or crash: close it at its last point so it can be finished on the server."""
        with db_lock:
            rows = db.execute("SELECT id, start_ts FROM walks WHERE end_ts IS NULL AND synced = 0").fetchall()
            for wid, start_ts in rows:
                last = db.execute("SELECT MAX(ts) FROM points WHERE walk_id = ?", (wid,)).fetchone()[0]
                db.execute("UPDATE walks SET end_ts = ? WHERE id = ?", (last or start_ts, wid))
            db.commit()

    # ---------- helpers ----------
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = p2 - p1, math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * R * math.asin(math.sqrt(a))

    def apply_walk_effects(meters):
        """Walking cheers the pet up and works up an appetite."""
        global hunger, happy
        happy = min(100, happy + meters * HAPPY_PER_METER)
        hunger = min(100, hunger + meters * HUNGER_PER_METER)

    def gps_epoch(msg):
        """UTC seconds from the GPS sentence itself. The Pi has no battery clock, so its own time can be wrong."""
        try:
            moment = msg.datetime
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return moment.timestamp()
        except Exception:
            return time.time()

    def iso(ts):
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()

    # ---------- live uploader ----------
    session = requests.Session()
    session.headers.update({"X-Demo-User-Id": USER})

    def mark_synced(wid):
        with db_lock:
            db.execute("UPDATE walks SET synced = 1 WHERE id = ?", (wid,))
            db.commit()

    def reset_server_walk(wid):
        """The backend no longer knows this walk (e.g. its database was reset): start over on the next pass."""
        with db_lock:
            db.execute("UPDATE walks SET server_id = NULL WHERE id = ?", (wid,))
            db.execute("UPDATE points SET sent = 0 WHERE walk_id = ?", (wid,))
            db.commit()
        print(f"backend lost walk {wid}; it will be re-created")

    def count_backlog():
        with db_lock:
            open_walks = db.execute("SELECT COUNT(*) FROM walks WHERE synced = 0").fetchone()[0]
            pending = db.execute(
                "SELECT COUNT(*) FROM points WHERE sent = 0 "
                "AND walk_id IN (SELECT id FROM walks WHERE synced = 0)"
            ).fetchone()[0]
        return open_walks, pending

    def sync_walk(wid, server_id, end_ts):
        """Bring one local walk up to date on the backend. Raises on network errors; the next pass retries."""
        created_now = False
        if server_id is None:
            with db_lock:
                total = db.execute("SELECT COUNT(*) FROM points WHERE walk_id = ?", (wid,)).fetchone()[0]
            if end_ts is not None and total == 0:       # finished without a single GPS fix: nothing worth sending
                mark_synced(wid)
                return
            r = session.post(f"{BASE}/walks/start", timeout=8)
            r.raise_for_status()
            server_id, created_now = r.json()["id"], True
            with db_lock:
                db.execute("UPDATE walks SET server_id = ? WHERE id = ?", (server_id, wid))
                db.commit()
            if VISIBILITY != "private":
                try:
                    session.patch(f"{BASE}/walks/{server_id}/sharing", timeout=8,
                                json={"visibility": VISIBILITY, "allow_follow_race": False})
                except requests.RequestException:
                    pass

        while True:
            with db_lock:
                rows = db.execute(
                    "SELECT rowid, ts, lat, lon, speed FROM points "
                    "WHERE walk_id = ? AND sent = 0 ORDER BY ts, rowid LIMIT 500", (wid,)
                ).fetchall()
            if not rows:
                break
            points = []
            for rowid, ts, lat, lon, speed in rows:
                point = {"client_point_id": f"p{rowid}", "latitude": lat, "longitude": lon,
                        "recorded_at": iso(ts)}
                if speed is not None:
                    point["speed_mps"] = speed
                points.append(point)
            r = session.post(f"{BASE}/walks/{server_id}/points/batch", json={"points": points}, timeout=10)
            if r.status_code == 404 and not created_now:
                reset_server_walk(wid)
                return
            if r.status_code == 409:                    # the backend closed this walk already: nothing more can be added
                print(f"backend walk {server_id} is already closed; dropping the rest of walk {wid}")
                mark_synced(wid)
                return
            r.raise_for_status()
            with db_lock:
                db.executemany("UPDATE points SET sent = 1 WHERE rowid = ?", [(row[0],) for row in rows])
                db.commit()

        if end_ts is not None:                          # the walk is over and every point is up: close it
            r = session.patch(f"{BASE}/walks/{server_id}", timeout=8)
            if r.status_code == 404 and not created_now:
                reset_server_walk(wid)
                return
            r.raise_for_status()
            mark_synced(wid)

    def sync_once():
        with db_lock:
            walks = db.execute("SELECT id, server_id, end_ts FROM walks WHERE synced = 0 ORDER BY id").fetchall()
        if not walks:                                   # idle: just confirm the backend is reachable
            session.get(f"{BASE}/", timeout=4).raise_for_status()
        for wid, server_id, end_ts in walks:
            sync_walk(wid, server_id, end_ts)
        net["open"], net["pending"] = count_backlog()
        net["ok"] = True

    def uploader_loop():
        last_error, last_print = None, 0.0
        while True:
            try:
                sync_once()
                last_error = None
            except Exception as e:
                net["ok"] = False
                net["open"], net["pending"] = count_backlog()
                if str(e) != last_error or time.time() - last_print > 30:   # don't flood the terminal while offline
                    print("upload:", e)
                    last_error, last_print = str(e), time.time()
            wake.wait(UPLOAD_SECONDS)
            wake.clear()

    # ---------- background threads ----------
    def decay_loop():
        global hunger, happy
        while True:
            time.sleep(DECAY_SECONDS)
            if state == "walk":        # out on a walk: the walk drives the stats instead
                continue
            hunger = min(100, hunger + 2)
            happy = max(0, happy - 1)
            if state == "pet":
                draw_menu()

    def anim_loop():
        global bounce, tick, cat
        while True:
            time.sleep(0.5)
            bounce = 2 - bounce
            tick = (tick + 1) % len(seq)
            cat = frames[seq[tick]]
            if state in ("main", "walk", "pet", "ready", "end"):
                draw_menu()

    def gps_loop():
        global distance_m, last_pos
        while True:
            try:
                ser = serial.Serial(GPS_PORT, 9600, timeout=1)
                while True:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if not line.startswith(("$GPRMC", "$GNRMC")):
                        continue
                    try:
                        msg = pynmea2.parse(line)
                    except pynmea2.ParseError:
                        continue
                    gps["fix"] = msg.status == "A"
                    if not gps["fix"]:
                        continue
                    pos = (msg.latitude, msg.longitude)
                    if state == "walk" and walk_id:
                        try:
                            speed = round(float(msg.spd_over_grnd) * 0.514444, 2)   # knots -> m/s
                        except (TypeError, ValueError):
                            speed = None
                        with db_lock:
                            db.execute("INSERT INTO points (walk_id, ts, lat, lon, speed) VALUES (?,?,?,?,?)",
                                    (walk_id, gps_epoch(msg), pos[0], pos[1], speed))
                            db.commit()
                        wake.set()                      # push it out now instead of waiting for the next pass
                    if state != "walk":
                        last_pos = None
                    elif last_pos is None:
                        last_pos = pos
                    else:
                        step = haversine(*last_pos, *pos)
                        if step > 3:                          # ignore jitter under 3 m
                            distance_m += step
                            apply_walk_effects(step)
                            last_pos = pos
            except Exception as e:
                gps["fix"] = False
                print("GPS error, retrying in 2 s:", e)
                time.sleep(2)

    # ---------- drawing ----------
    def _render():
        with lock:
            with canvas(device) as draw:
                if state == "main":
                    x = (device.width - cat.width) // 2
                    draw.bitmap((x, 3 + bounce), cat, fill="white")
                    label = menus["main"][cursor]
                    w = draw.textlength(label)
                    draw.text(((device.width - w) / 2, 50), label, fill="white")
                elif state == "pet":
                    face = frames["happy"] if time.time() < react_until else cat
                    draw.bitmap((90, 4 + bounce), face, fill="white")
                    for i, name in enumerate(menus[state]):
                        prefix = "> " if i == cursor else "  "
                        draw.text((4, 5 + i * 12), prefix + name, fill="white")
                    draw.text((4, 50), f"H:{hunger:.0f} Happy:{happy:.0f}", fill="white")
                elif state == "ready":
                    draw.bitmap((5, 12 + bounce), cat, fill="white")
                    draw.text((44, 8), "Ready?", fill="white")
                    draw.text((44, 22), "Click to go", fill="white")
                    draw.text((44, 36), "GPS: Locked" if gps["fix"] else "GPS: Searching", fill="white")
                    draw.text((44, 50), "Net: ok" if net["ok"] else "Net: --", fill="white")
                elif state == "walk":
                    draw.bitmap((5, 12 + bounce), cat, fill="white")
                    secs = int(time.monotonic() - walk_t0)
                    draw.text((44, 6), f"Time: {secs // 60}:{secs % 60:02d}", fill="white")
                    draw.text((44, 20), f"Dist: {distance_m / 1609.344:.2f} mi", fill="white")
                    draw.text((44, 34), "GPS: Locked" if gps["fix"] else "GPS: Searching", fill="white")
                    draw.text((44, 48), "Live: ok" if net["ok"] else f"Live: -- ({net['pending']})", fill="white")
                elif state == "end":
                    draw.text((4, 4), f"{distance_m / 1609.344:.2f} mi  {walk_secs // 60}:{walk_secs % 60:02d}", fill="white")
                    if net["ok"] and net["open"] == 0:
                        status = "Synced"
                    elif net["ok"]:
                        status = f"Uploading ({net['pending']})"
                    else:
                        status = f"Offline, queued {net['pending']}"
                    draw.text((4, 22), status, fill="white")
                    draw.text((4, 50), "Click to exit", fill="white")

    def draw_menu():
        try:
            _render()
        except Exception as e:      # e.g. a transient I2C error
            print("draw error:", e)

    # ---------- walk lifecycle ----------
    def start_walk():
        global state, walk_t0, distance_m, last_pos, walk_id
        distance_m, last_pos = 0.0, None
        with db_lock:
            cur = db.execute("INSERT INTO walks (start_ts) VALUES (?)", (time.time(),))
            db.commit()
            walk_id = cur.lastrowid
        walk_t0 = time.monotonic()
        state = "walk"
        wake.set()                  # create the walk on the backend right away
        draw_menu()

    def end_walk():
        global state, walk_secs
        walk_secs = int(time.monotonic() - walk_t0)
        state = "end"               # the GPS thread stops adding points to this walk
        with db_lock:
            db.execute("UPDATE walks SET end_ts = ?, distance_m = ? WHERE id = ?",
                    (time.time(), distance_m, walk_id))
            db.commit()
        wake.set()                  # send what is left and close the walk on the backend
        draw_menu()

    # ---------- button handling ----------
    def select():
        global state, cursor, hunger, happy, react_until
        if state == "end":                     # leave the summary screen
            state, cursor = "main", 0
            draw_menu()
            return
        if state == "ready":                   # long press cancels back to the menu
            state = "main"
            draw_menu()
            return
        if state == "walk":                    # long press ends the walk
            end_walk()
            return
        choice = menus[state][cursor]
        if state == "main":
            if choice == "Buddy":
                state, cursor = "pet", 0
            elif choice == "Start Walk":
                state = "ready"
        elif state == "pet":
            if choice == "Feed":
                hunger = max(0, hunger - 20)
                react_until = time.time() + 2
            elif choice == "Pet":
                happy = min(100, happy + 10)
                react_until = time.time() + 2
            elif choice == "Back":
                state, cursor = "main", 0
        draw_menu()

    def on_held():
        global held
        held = True
        try:
            select()
        except Exception:
            traceback.print_exc()

    def on_released():
        global held, cursor, state
        if not held:
            try:
                if state == "ready":           # a short click starts the walk
                    start_walk()
                elif state == "end":
                    state, cursor = "main", 0
                    draw_menu()
                elif state in menus:
                    cursor = (cursor + 1) % len(menus[state])
                    draw_menu()
            except Exception:
                traceback.print_exc()
        held = False

    btn.when_held = on_held
    btn.when_released = on_released

    # ---------- start ----------
    init_db()
    recover_unfinished()
    threading.Thread(target=decay_loop, daemon=True).start()
    threading.Thread(target=anim_loop, daemon=True).start()
    threading.Thread(target=gps_loop, daemon=True).start()
    threading.Thread(target=uploader_loop, daemon=True).start()

    draw_menu()
    pause()
except KeyboardInterrupt:
    pass