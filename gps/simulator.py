import argparse
import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def api_request(url: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a fake hiking trail to TrailBuddy.")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--walk-id", help="Use an existing active walk")
    parser.add_argument("--latitude", type=float, default=40.7128)
    parser.add_argument("--longitude", type=float, default=-74.0060)
    parser.add_argument("--points", type=int, default=30)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    try:
        walk_id = args.walk_id
        if not walk_id:
            walk_id = api_request(f"{args.api}/walks/start", method="POST")["id"]
            print(f"Started walk {walk_id}")

        for index in range(args.points):
            point = {
                "latitude": args.latitude + index * 0.00008 + math.sin(index / 3) * 0.00015,
                "longitude": args.longitude + index * 0.00010 + math.cos(index / 4) * 0.00012,
            }
            saved = api_request(
                f"{args.api}/walks/{walk_id}/points",
                method="POST",
                payload=point,
            )
            print(
                f"Point {saved['id']}: "
                f"{saved['latitude']:.6f}, {saved['longitude']:.6f}"
            )
            time.sleep(args.interval)

        print(f"Open {args.api}/app/ to see the trail.")
    except (HTTPError, URLError) as error:
        raise SystemExit(f"TrailBuddy API request failed: {error}") from error


if __name__ == "__main__":
    main()
