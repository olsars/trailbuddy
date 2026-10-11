from PIL import Image

def load_sprite(path, cells=(34, 36)):
    img = Image.open(path).convert("L")
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

import time
from gpiozero import Button
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas
import threading
lock = threading.Lock()
import math
import serial
import pynmea2
import sqlite3
import os

device = ssd1306(i2c(port=1, address=0x3C))

btn = Button(17, hold_time=0.8)
held = False

menus = {
    "main": ["Buddy", "Start Walk"],
    "pet":  ["Feed", "Pet", "Back"],
    "end": ["Keep", "Delete"],
}
state = "main"
cursor = 0
hunger = 50      # 0 = full, 100 = starving
happy = 50       # 0 = sad, 100 = happy
walk_start = 0
react_until = 0

db = sqlite3.connect(os.path.expanduser("~/trailbuddy.db"), check_same_thread=False)
db_lock = threading.Lock()
db.executescript("""
CREATE TABLE IF NOT EXISTS walks (id INTEGER PRIMARY KEY, start_ts REAL, end_ts REAL, distance_m REAL);
CREATE TABLE IF NOT EXISTS points (walk_id INTEGER, ts REAL, lat REAL, lon REAL);
""")
walk_id = None
walk_secs = 0
distance_m = 0.0
last_pos = None
gps = {"fix": False}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

DECAY_SECONDS = 30   # slow this down later (30+) for real use

def decay_loop():
    global hunger, happy
    while True:
        time.sleep(DECAY_SECONDS)
        hunger = min(100, hunger + 2)
        happy = max(0, happy - 1)
        if state == "pet":
            draw_menu()

threading.Thread(target=decay_loop, daemon=True).start()

def anim_loop():
    global bounce, tick, cat
    while True:
        time.sleep(0.5)
        bounce = 2 - bounce
        tick = (tick + 1) % len(seq)
        cat = frames[seq[tick]]
        if state in ("main", "walk", "pet", "ready"):
            draw_menu()

threading.Thread(target=anim_loop, daemon=True).start()

def gps_loop():
    global distance_m, last_pos
    ser = serial.Serial("/dev/ttyAMA0", 9600, timeout=1)
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
            with db_lock:
                db.execute("INSERT INTO points VALUES (?,?,?,?)", (walk_id, time.time(), *pos))
                db.commit()
        if state != "walk":
            last_pos = None
        elif last_pos is None:
            last_pos = pos
        elif haversine(*last_pos, *pos) > 3:      # ignore jitter under 3 m
            distance_m += haversine(*last_pos, *pos)
            last_pos = pos

threading.Thread(target=gps_loop, daemon=True).start()

def draw_menu():
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
                draw.text((4, 50), f"H:{hunger} Happy:{happy}", fill="white")
            elif state == "walk":
                draw.bitmap((5, 12 + bounce), cat, fill="white")
                secs = int(time.time() - walk_start)
                draw.text((44, 18), f"Time: {secs // 60}:{secs % 60:02d}", fill="white")
                draw.text((44, 34), f"Dist: {distance_m / 1609.344:.2f} mi", fill="white")
                draw.text((44, 48), "GPS: Locked" if gps["fix"] else "GPS: Searching", fill="white")
            elif state == "ready":
                draw.bitmap((5, 12 + bounce), cat, fill="white")
                draw.text((44, 18), "Ready?", fill="white")
                draw.text((44, 34), "Click to go", fill="white")
                draw.text((44, 48), "Locked" if gps["fix"] else "Searching", fill="white")
            elif state == "end":
                draw.text((4, 2), f"{distance_m / 1609.344:.2f} mi  {walk_secs // 60}:{walk_secs % 60:02d}", fill="white")
                for i, name in enumerate(menus["end"]):
                    prefix = "> " if i == cursor else "  "
                    draw.text((4, 20 + i * 12), prefix + name, fill="white")

def start_walk():
    global state, walk_start, distance_m, last_pos, walk_id
    state = "walk"
    walk_start = time.time()
    distance_m, last_pos = 0.0, None
    with db_lock:
        cur = db.execute("INSERT INTO walks (start_ts) VALUES (?)", (walk_start,))
        db.commit()
        walk_id = cur.lastrowid
    draw_menu()

def end_walk():
    global state, cursor, walk_secs
    walk_secs = int(time.time() - walk_start)
    with db_lock:
        db.execute("UPDATE walks SET end_ts=?, distance_m=? WHERE id=?",
                   (time.time(), distance_m, walk_id))
        db.commit()
    state, cursor = "end", 0
    draw_menu()

def delete_walk():
    with db_lock:
        db.execute("DELETE FROM points WHERE walk_id=?", (walk_id,))
        db.execute("DELETE FROM walks WHERE id=?", (walk_id,))
        db.commit()

def select():
    global state, cursor, hunger, happy, react_until
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
    elif state == "end":
        if choice == "Keep":
            state, cursor = "main", 0
        elif choice == "Delete":
            delete_walk()
            state, cursor = "main", 0
    draw_menu()

def show(msg):
    with canvas(device) as draw:
        draw.text((10, 25), msg, fill="white")

def on_held():
    global held
    held = True
    select()

def on_released():
    global held, cursor
    if not held:
        if state == "ready":               # a short click starts the walk
            start_walk()
        elif state in menus:
            cursor = (cursor + 1) % len(menus[state])
            draw_menu()
    held = False

btn.when_held = on_held
btn.when_released = on_released

from signal import pause
draw_menu()
pause()