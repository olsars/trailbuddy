import math
import os
import queue
import socket
import sqlite3
import subprocess
import threading
import time
import traceback
from datetime import datetime, timezone
from signal import pause
from urllib.parse import urlparse

import pynmea2
import requests
import serial
from gpiozero import Button, PWMOutputDevice
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import Image

# ---------- config (override with environment variables) ----------
BASE = os.environ.get("TRAILBUDDY_API", "http://192.168.135.63:8000").rstrip("/")
USER = os.environ.get("TRAILBUDDY_USER", "pablo")
VISIBILITY = os.environ.get("TRAILBUDDY_VISIBILITY", "private")   # private | friends | public
GPS_PORT = os.environ.get("TRAILBUDDY_GPS_PORT", "/dev/ttyAMA0")
DB_PATH = os.path.expanduser(os.environ.get("TRAILBUDDY_DB", "~/trailbuddy.db"))
HERE = os.path.dirname(os.path.abspath(__file__))
DECAY_SECONDS = 30      # seconds between pet stat decay ticks
UPLOAD_SECONDS = 2      # how often the live uploader checks for new points
HAPPY_PER_METER = 0.10  # walking: +1 happiness per 10 m
HUNGER_PER_METER = 0.05 # walking: +1 hunger per 20 m
# GPS trail filters: a receiver reports "valid" fixes indoors and between tall buildings that wander
# tens of metres while you stand still. These keep that drift off the trail.
MIN_MOVING_MPS = 0.6    # below this speed (about 1.3 mph) you are standing still: ignore position changes
MAX_WALK_MPS = 7.0      # a jump implying more than this (about 15 mph) is a GPS glitch, not you
MIN_SATS = 4            # fewer satellites than this: don't put the fix on the trail (4 = minimum for a 3D fix)
MAX_HDOP = 5.0          # HDOP above this (very poor satellite geometry): don't put the fix on the trail
DEBUG = os.environ.get("TRAILBUDDY_DEBUG") == "1"   # print every 5 s why GPS fixes are kept or dropped
HEARTBEAT_SECONDS = 30  # standing still: re-send the last good position this often, so the page does not call it stale (it does after 5 min)
SPLASH_SECONDS = 3.6    # how long the start screen shows (any button press skips it)
BUZZER_PIN = os.environ.get("TRAILBUDDY_BUZZER_PIN", "27")   # BCM number (27 = header pin 13); "off" turns sound off

def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default

VOLUME = max(0.1, min(1.0, _env_float("TRAILBUDDY_VOLUME", 1.0)))   # 1.0 = loudest; lower is quieter

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

    # ---------- sound (a passive buzzer or speaker on one GPIO pin) ----------
    MELODIES = {                              # (frequency in Hz, seconds); 0 = a rest
        "boot":       [(784, .12), (988, .12), (1319, .12), (1568, .24)],      # the cat waking up
        "click":      [(1800, .02)],
        "select":     [(2400, .045)],
        "walk_start": [(1047, .10), (1568, .20)],                              # rising
        "walk_end":   [(1568, .10), (1047, .22)],                              # falling
        "gps_lock":   [(1319, .09), (1760, .18)],
        "happy":      [(1568, .06), (2093, .06), (1568, .06), (2093, .12)],
        "on":         [(1760, .08)],
    }

    class Sound:
        """Plays short melodies in the background, so they never hold up the screen or the button."""

        def __init__(self, device, volume=1.0):
            self.dev, self.duty = device, 0.5 * volume      # a square wave is loudest at 50% duty
            self.enabled = True
            self.busy = False
            self.q = queue.Queue(maxsize=6)
            if device is not None:
                threading.Thread(target=self._run, daemon=True).start()

        def play(self, name):
            if not self.enabled or self.dev is None:
                return
            if name in ("click", "select") and (self.busy or not self.q.empty()):
                return                                      # a tick must not interrupt or queue behind a melody
            try:
                self.q.put_nowait(name)
            except queue.Full:
                pass

        def _run(self):
            while True:
                name = self.q.get()
                self.busy = True
                try:
                    for freq, secs in MELODIES[name]:
                        if not self.enabled:
                            break
                        if freq:
                            self.dev.frequency = freq
                            self.dev.value = self.duty
                        else:
                            self.dev.value = 0
                        time.sleep(secs)
                    self.dev.value = 0
                except Exception as e:                      # e.g. the pin went away: stay quiet instead of crashing
                    print("sound error, sound is off:", e)
                    self.dev = None
                finally:
                    self.busy = False

    def make_sound():
        if BUZZER_PIN.strip().lower() in ("", "off", "none", "0"):
            return Sound(None)
        try:
            device = PWMOutputDevice(int(BUZZER_PIN), frequency=1000, initial_value=0)   # silent until a note plays
        except Exception as e:
            print("no sound:", e)
            device = None
        return Sound(device, VOLUME)

    sound = make_sound()

    # ---------- state ----------
    menus = {
        "main": ["> Buddy <", "> Start Walk <", "> Phone link <", "> Sound <"],
        "pet":  ["- Feed", "- Pet", "- Back"],
    }
    state = "splash"        # splash | main | pet | ready | walk | end | info
    splash_t0 = time.monotonic()
    cursor = 0
    hunger = 50             # 0 = full, 100 = starving
    happy = 50              # 0 = sad, 100 = happy
    react_until = 0

    walk_id = None          # local id of the walk in progress
    walk_t0 = 0.0           # time.monotonic() at start (immune to the Pi's clock being corrected)
    walk_secs = 0
    distance_m = 0.0
    last_pos = None
    last_ts = 0.0
    last_rec = 0.0          # GPS time of the last point put on the trail
    rejects = 0
    gps = {"fix": False, "good": False, "sats": None, "hdop": None}
    stats = {"fixes": 0, "saved": 0, "still": 0, "jump": 0, "poor": 0, "beat": 0, "t": 0.0}   # per-walk counters for DEBUG
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
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
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

    def get_setting(key, default=None):
        with db_lock:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(key, value):
        with db_lock:
            db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
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
        global bounce, tick, cat, state
        while True:
            time.sleep(0.5)
            bounce = 2 - bounce
            tick = (tick + 1) % len(seq)
            cat = frames[seq[tick]]
            if state == "splash" and time.monotonic() - splash_t0 >= SPLASH_SECONDS:
                state = "main"
            if state in ("splash", "main", "walk", "pet", "ready", "end"):
                draw_menu()

    def to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def quality_ok():
        """Enough satellites with decent geometry? Values the receiver hasn't reported don't count against it."""
        sats, hdop = gps["sats"], gps["hdop"]
        return (sats is None or sats >= MIN_SATS) and (hdop is None or hdop <= MAX_HDOP)

    def reset_track():
        global last_pos, last_ts, last_rec, rejects
        last_pos, last_ts, last_rec, rejects = None, 0.0, 0.0, 0

    def handle_fix(pos, ts, speed):
        """Decide whether a GPS fix belongs on the trail. Returns the position to record, or None to skip it."""
        global distance_m, last_pos, last_ts, last_rec, rejects
        if last_pos is None:                          # first usable fix of the walk: anchor the trail here
            last_pos, last_ts, last_rec = pos, ts, ts
            return pos
        if speed is not None and speed < MIN_MOVING_MPS:
            stats["still"] += 1
            last_ts, rejects = ts, 0                  # standing still: position changes are drift. Time still
            if ts - last_rec >= HEARTBEAT_SECONDS:    # passes, so a later jump is judged against *now*
                last_rec = ts                         # still alive: re-send where we were, not where the drift says
                stats["beat"] += 1
                return last_pos
            return None
        step = haversine(*last_pos, *pos)
        if step / max(ts - last_ts, 1.0) > MAX_WALK_MPS:
            stats["jump"] += 1
            rejects += 1                              # a jump no walker could make: a GPS glitch
            last_ts = ts                              # keep judging it against *now*, or it looks more plausible each second
            if rejects < 5:
                return None
            last_pos, last_ts, last_rec, rejects = pos, ts, ts, 0   # five in a row: believe it, restart from here
            return pos
        rejects = 0
        if step > 3:                                  # distance only counts real steps
            distance_m += step
            apply_walk_effects(step)
            last_pos, last_ts = pos, ts
        last_rec = ts
        return pos

    def debug_report(speed):
        if not DEBUG or state not in ("ready", "walk") or time.time() - stats["t"] < 5:
            return
        stats["t"] = time.time()
        print(f"GPS [{state}] fix={gps['fix']} good={gps['good']} sats={gps['sats']} hdop={gps['hdop']} speed={speed} m/s | fixes {stats['fixes']} "
              f"saved {stats['saved']} (heartbeats {stats['beat']}) still {stats['still']} jump {stats['jump']} poor {stats['poor']}")

    def gps_loop():
        was_good, chime_t = False, 0.0
        while True:
            try:
                ser = serial.Serial(GPS_PORT, 9600, timeout=1)
                while True:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if line.startswith(("$GPGGA", "$GNGGA")):       # satellite count and HDOP (lower is better)
                        try:
                            gga = pynmea2.parse(line)
                        except pynmea2.ParseError:
                            continue
                        gps["sats"] = to_float(gga.num_sats)
                        gps["hdop"] = to_float(gga.horizontal_dil)
                        continue
                    if not line.startswith(("$GPRMC", "$GNRMC")):
                        continue
                    try:
                        msg = pynmea2.parse(line)
                    except pynmea2.ParseError:
                        continue
                    knots = to_float(msg.spd_over_grnd)
                    speed = round(knots * 0.514444, 2) if knots is not None else None   # knots -> m/s
                    valid = msg.status == "A"
                    gps["fix"] = valid
                    gps["good"] = valid and quality_ok()
                    if gps["good"] and not was_good and state in ("ready", "walk") and time.time() - chime_t > 30:
                        chime_t = time.time()
                        sound.play("gps_lock")
                    was_good = gps["good"]
                    walking = state == "walk" and walk_id
                    if walking and valid:
                        stats["fixes"] += 1
                        if not gps["good"]:
                            stats["poor"] += 1
                    debug_report(speed)
                    if not gps["good"]:
                        continue
                    if not walking:
                        reset_track()
                        continue
                    ts = gps_epoch(msg)
                    recorded = handle_fix((msg.latitude, msg.longitude), ts, speed)
                    if recorded:
                        stats["saved"] += 1
                        with db_lock:
                            db.execute("INSERT INTO points (walk_id, ts, lat, lon, speed) VALUES (?,?,?,?,?)",
                                    (walk_id, ts, recorded[0], recorded[1], speed))
                            db.commit()
                        wake.set()                      # push it out now instead of waiting for the next pass
            except Exception as e:
                gps["fix"] = gps["good"] = False
                print("GPS error, retrying in 2 s:", e)
                time.sleep(2)

    def label_for(choice):
        if choice == "> Sound <":
            return "> Sound: on <" if sound.enabled else "> Sound: off <"
        return choice

    def toggle_sound():
        sound.enabled = not sound.enabled
        set_setting("sound", "on" if sound.enabled else "off")
        sound.play("on")                    # a blip confirms it (and is silent when you just muted)

    # ---------- phone link (where to point a phone's browser) ----------
    info = {"host": None, "port": 8000}

    def local_ip():
        """This Pi's address on the network it is connected to (the phone's hotspot)."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(("10.255.255.255", 1))     # sends nothing; only reveals which interface would be used
                return sock.getsockname()[0]
            finally:
                sock.close()
        except OSError:
            pass
        try:
            return subprocess.check_output(["hostname", "-I"], text=True, timeout=2).split()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            return None

    def refresh_info():
        """The server a phone should open: this Pi when the backend runs here, otherwise the remote backend."""
        parts = urlparse(BASE)
        host = parts.hostname or "127.0.0.1"
        info["port"] = parts.port or 8000
        info["host"] = local_ip() if host in ("127.0.0.1", "localhost", "::1") else host

    # ---------- drawing ----------
    def gps_label():
        if gps["good"]:
            return "GPS: Locked"
        return "GPS: Weak" if gps["fix"] else "GPS: Searching"     # Weak = a fix, but too few satellites / poor geometry

    def _render():
        with lock:
            with canvas(device) as draw:
                if state == "main":
                    x = (device.width - cat.width) // 2
                    draw.bitmap((x, 3 + bounce), cat, fill="white")
                    label = label_for(menus["main"][cursor])
                    w = draw.textlength(label)
                    draw.text(((device.width - w) / 2, 50), label, fill="white")
                elif state == "pet":
                    face = frames["happy"] if time.time() < react_until else cat
                    draw.bitmap((90, 4 + bounce), face, fill="white")
                    for i, name in enumerate(menus[state]):
                        prefix = "> " if i == cursor else "  "
                        draw.text((4, 5 + i * 12), prefix + name, fill="white")
                    draw.text((4, 50), f"H:{hunger:.0f} Happy:{happy:.0f}", fill="white")
                elif state == "splash":
                    t = time.monotonic() - splash_t0
                    if t < 1.2:
                        face, line = frames["blink"], "zzz..."
                    elif t < 2.4:
                        face, line = frames["idle"], "Waking up..."
                    else:
                        face, line = frames["happy"], "Let's go for a walk!"
                    title = "TrailBuddy"
                    draw.text(((device.width - draw.textlength(title)) / 2, 0), title, fill="white")
                    draw.bitmap(((device.width - face.width) // 2, 13), face, fill="white")
                    draw.text(((device.width - draw.textlength(line)) / 2, 52), line, fill="white")
                elif state == "ready":
                    draw.bitmap((5, 12 + bounce), cat, fill="white")
                    draw.text((44, 8), "Ready?", fill="white")
                    draw.text((44, 22), "Click to go", fill="white")
                    draw.text((44, 36), gps_label(), fill="white")
                    draw.text((44, 50), "Net: ok" if net["ok"] else "Net: --", fill="white")
                elif state == "walk":
                    draw.bitmap((5, 12 + bounce), cat, fill="white")
                    secs = int(time.monotonic() - walk_t0)
                    draw.text((44, 6), f"Time: {secs // 60}:{secs % 60:02d}", fill="white")
                    draw.text((44, 20), f"Dist: {distance_m / 1609.344:.2f} mi", fill="white")
                    draw.text((44, 34), gps_label(), fill="white")
                    draw.text((44, 48), "Live: ok" if net["ok"] else f"Live: -- ({net['pending']})", fill="white")
                elif state == "info":
                    draw.text((4, 4), "Open on a phone:", fill="white")
                    if info["host"]:
                        draw.text((4, 20), f"{info['host']}:{info['port']}", fill="white")
                        draw.text((4, 34), f"/app/?user={USER}", fill="white")
                    else:
                        draw.text((4, 20), "No network yet", fill="white")
                    draw.text((4, 50), "Click to exit", fill="white")
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
        global state, walk_t0, distance_m, walk_id
        distance_m = 0.0
        reset_track()
        for key in stats:
            stats[key] = 0
        with db_lock:
            cur = db.execute("INSERT INTO walks (start_ts) VALUES (?)", (time.time(),))
            db.commit()
            walk_id = cur.lastrowid
        walk_t0 = time.monotonic()
        state = "walk"
        sound.play("walk_start")
        wake.set()                  # create the walk on the backend right away
        draw_menu()

    def end_walk():
        global state, walk_secs
        walk_secs = int(time.monotonic() - walk_t0)
        state = "end"               # the GPS thread stops adding points to this walk
        sound.play("walk_end")
        with db_lock:
            db.execute("UPDATE walks SET end_ts = ?, distance_m = ? WHERE id = ?",
                    (time.time(), distance_m, walk_id))
            db.commit()
        wake.set()                  # send what is left and close the walk on the backend
        draw_menu()

    # ---------- button handling ----------
    def select():
        global state, cursor, hunger, happy, react_until
        if state == "splash":                  # any press skips the start screen
            state = "main"
            draw_menu()
            return
        if state in ("end", "info"):           # leave the summary / phone-link screen
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
            if choice == "> Buddy <":
                state, cursor = "pet", 0
            elif choice == "> Start Walk <":
                state = "ready"
            elif choice == "> Phone link <":
                refresh_info()
                state = "info"
            elif choice == "> Sound <":
                toggle_sound()
        elif state == "pet":
            if choice == "- Feed":
                hunger = max(0, hunger - 20)
                react_until = time.time() + 2
                sound.play("happy")
            elif choice == "- Pet":
                happy = min(100, happy + 10)
                react_until = time.time() + 2
                sound.play("happy")
            elif choice == "- Back":
                state, cursor = "main", 0
        draw_menu()

    def on_held():
        global held
        held = True
        sound.play("select")
        try:
            select()
        except Exception:
            traceback.print_exc()

    def on_released():
        global held, cursor, state
        if not held:
            try:
                sound.play("click")
                if state == "splash":          # any press skips the start screen
                    state = "main"
                    draw_menu()
                elif state == "ready":         # a short click starts the walk
                    start_walk()
                elif state in ("end", "info"):
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
    sound.enabled = get_setting("sound", "on") == "on"
    splash_t0 = time.monotonic()            # the start screen's clock begins now, not while the sprites were loading
    threading.Thread(target=decay_loop, daemon=True).start()
    threading.Thread(target=anim_loop, daemon=True).start()
    threading.Thread(target=gps_loop, daemon=True).start()
    threading.Thread(target=uploader_loop, daemon=True).start()

    sound.play("boot")
    draw_menu()
    pause()
except KeyboardInterrupt:
    pass