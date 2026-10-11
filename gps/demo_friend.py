"""Plays a friend who is out walking, so the friends feature can be shown off.

It uses one of the built-in demo profiles as the stand-in friend (default: laeh) and, against a running backend:
  1. makes them friends with you (accepting the pending request, or sending and accepting a new one),
  2. has the friend share their location with you,
  3. starts a walk for the friend and walks a loop near you in real time,
  4. ends that walk when you press Ctrl+C.

    python3 gps/demo_friend.py                       # backend on this machine, you are "pablo"
    python3 gps/demo_friend.py --setup-only          # leave a finished route behind and exit
    python3 gps/demo_friend.py --api http://192.168.1.20:8000 --friend sam

Safe to run again and again: it never duplicates the friendship, and it ends any walk a previous run left open.
"""

import argparse
import json
import math
import signal
import sys
import time
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CENTER = (28.6013, -81.1990)    # UCF, near the Business Administration building
METERS_PER_DEGREE_LAT = 111320.0


class ApiError(Exception):
    pass


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, user: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, method=method)
        request.add_header("X-Demo-User-Id", user)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=10) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode(errors="ignore")[:200]
            raise ApiError(f"{method} {path} (as {user}) returned {error.code}: {detail}") from None
        except URLError as error:
            raise ApiError(f"cannot reach the backend at {self.base} ({error.reason})") from None
        return json.loads(raw) if raw else None


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


class Loop:
    """A closed, slightly irregular loop (like a path round a block) that can be walked at a steady speed."""

    def __init__(self, center: tuple[float, float], radius_m: float, steps: int = 720):
        lat0, lon0 = center
        meters_per_degree_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians(lat0))
        self.points = []
        for i in range(steps + 1):                       # the last point repeats the first, closing the loop
            t = 2 * math.pi * (i % steps) / steps
            east = radius_m * (math.cos(t) + 0.12 * math.cos(3 * t))
            north = radius_m * 0.7 * (math.sin(t) - 0.10 * math.sin(2 * t))
            self.points.append((lat0 + north / METERS_PER_DEGREE_LAT, lon0 + east / meters_per_degree_lon))
        self.cumulative = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cumulative.append(self.cumulative[-1] + haversine(a, b))
        self.length = self.cumulative[-1]

    def at(self, distance_m: float) -> tuple[float, float]:
        d = distance_m % self.length
        i = min(bisect_right(self.cumulative, d) - 1, len(self.points) - 2)
        span = self.cumulative[i + 1] - self.cumulative[i]
        f = (d - self.cumulative[i]) / span if span else 0.0
        (la, lo), (lb, lob) = self.points[i], self.points[i + 1]
        return round(la + (lb - la) * f, 7), round(lo + (lob - lo) * f, 7)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def ensure_friendship(api: Api, me: str, friend: str) -> None:
    if any(entry["id"] == friend for entry in api.call("GET", "/friends", me)):
        print(f"  {friend} is already your friend")
        return
    pending = [
        request for request in api.call("GET", "/friend-requests", me)
        if request["status"] == "pending" and {request["requester_id"], request["recipient_id"]} == {me, friend}
    ]
    request = pending[0] if pending else api.call("POST", "/friend-requests", me, {"recipient_id": friend})
    api.call("PATCH", f"/friend-requests/{request['id']}/accept", request.get("recipient_id", friend))
    print(f"  {friend} and {me} are now friends")


def end_open_walks(api: Api, user: str) -> None:
    """A walk left open by a run that was killed would show the friend as 'walking now' forever."""
    for walk in api.call("GET", "/walks", user):
        if walk["status"] == "active":
            api.call("PATCH", f"/walks/{walk['id']}", user)
            print("  ended a walk left open by an earlier run")


def pick_center(api: Api, me: str, latitude: float | None, longitude: float | None):
    if latitude is not None and longitude is not None:
        return (latitude, longitude), "the coordinates you gave"
    try:
        location = api.call("GET", f"/locations/{me}", me).get("last_location")
    except ApiError:
        location = None
    if location:                                          # a little north of you, so the two routes do not overlap
        return (location["latitude"] + 40 / METERS_PER_DEGREE_LAT, location["longitude"]), f"near {me}'s last location"
    return DEFAULT_CENTER, "the UCF default (you have no location yet)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Play a friend who is out walking.")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="backend address")
    parser.add_argument("--friend", default="laeh", help="demo profile that plays the friend (default: laeh)")
    parser.add_argument("--with", dest="me", default="pablo", help="your demo profile (default: pablo)")
    parser.add_argument("--latitude", type=float, help="centre of the walk (default: near your last location)")
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--radius", type=float, default=60.0, help="size of the loop in metres (default 60)")
    parser.add_argument("--speed", type=float, default=1.4, help="walking speed in m/s (default 1.4)")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between GPS points (default 2)")
    parser.add_argument("--duration", type=float, help="stop after this many seconds (default: until Ctrl+C)")
    parser.add_argument("--visibility", default="friends", choices=["private", "friends", "public"])
    parser.add_argument("--setup-only", action="store_true",
                        help="make the friendship and leave a finished route behind, without a live walk")
    args = parser.parse_args()

    if args.friend == args.me:
        print("The friend and you must be different profiles.")
        return 1
    api, me, friend = Api(args.api), args.me, args.friend

    stop = {"now": False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.update(now=True))

    try:
        print(f"Setting up {friend} as {me}'s friend on {api.base}")
        ensure_friendship(api, me, friend)
        api.call("PATCH", f"/location-sharing/{me}", friend, {"enabled": True})
        print(f"  {friend} is sharing their location with {me}")
        end_open_walks(api, friend)

        center, why = pick_center(api, me, args.latitude, args.longitude)
        loop = Loop(center, args.radius)
        print(f"  walking a {loop.length:.0f} m loop around {center[0]:.5f}, {center[1]:.5f} ({why})")

        walk = api.call("POST", "/walks/start", friend)
        walk_id = walk["id"]
        api.call("PATCH", f"/walks/{walk_id}/sharing", friend,
                 {"visibility": args.visibility, "allow_follow_race": False})

        # a trail behind them already, so the route is on the map the moment the page opens
        backlog = 150 if args.setup_only else 60
        step = args.speed * args.interval
        started_at = datetime.now(timezone.utc)
        points = []
        for i in range(backlog):
            moment = started_at - timedelta(seconds=args.interval * (backlog - i))
            lat, lon = loop.at(step * i)
            points.append(point(friend, moment, lat, lon, args.speed))
        api.call("POST", f"/walks/{walk_id}/points/batch", friend, {"points": points})
        walked = step * backlog

        if not args.setup_only:
            print(f"{friend} is out walking. Press Ctrl+C to end the walk.")
            t0 = time.monotonic()
            next_tick = t0 + args.interval
            count = backlog
            while not stop["now"]:
                elapsed = time.monotonic() - t0
                if args.duration is not None and elapsed >= args.duration:
                    break
                if time.monotonic() < next_tick:
                    time.sleep(0.05)
                    continue
                next_tick += args.interval
                lat, lon = loop.at(walked + args.speed * elapsed)
                try:
                    api.call("POST", f"/walks/{walk_id}/points/batch", friend,
                             {"points": [point(friend, datetime.now(timezone.utc), lat, lon, args.speed)]})
                    count += 1
                    if count % 5 == 0:
                        print(f"  {friend}: point {count} at {lat:.5f}, {lon:.5f}")
                except ApiError as error:                 # a hiccup must not end the show
                    print(f"  (skipped a point: {error})")

        result = api.call("PATCH", f"/walks/{walk_id}", friend)
        summary = result.get("summary") or {}
        print(f"Walk ended: {summary.get('point_count', '?')} points, {summary.get('distance_meters', '?')} m.")
        return 0
    except ApiError as error:
        print(f"Problem: {error}")
        return 1


def point(friend: str, moment: datetime, lat: float, lon: float, speed: float) -> dict:
    return {
        "client_point_id": f"demo-{friend}-{int(moment.timestamp() * 1000)}",
        "latitude": lat,
        "longitude": lon,
        "recorded_at": iso(moment),
        "speed_mps": speed,
        "accuracy_meters": 6.0,
    }


if __name__ == "__main__":
    sys.exit(main())