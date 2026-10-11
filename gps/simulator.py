import argparse
import json
import math
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def api_request(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    user_id: str = "sam",
):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, method=method)
    request.add_header("X-Demo-User-Id", user_id)
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
    parser.add_argument("--user", default="sam", help="Demo user id")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Queue GPS points locally, then upload them in one offline-safe batch",
    )
    args = parser.parse_args()

    try:
        walk_id = args.walk_id
        if not walk_id:
            walk_id = api_request(
                f"{args.api}/walks/start",
                method="POST",
                user_id=args.user,
            )["id"]
            print(f"Started walk {walk_id}")

        queued_points = []
        for index in range(args.points):
            point = {
                "client_point_id": f"sim-{walk_id}-{index}",
                "latitude": args.latitude + index * 0.00008 + math.sin(index / 3) * 0.00015,
                "longitude": args.longitude + index * 0.00010 + math.cos(index / 4) * 0.00012,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            if args.batch:
                queued_points.append(point)
                print(
                    f"Queued point {index + 1}: "
                    f"{point['latitude']:.6f}, {point['longitude']:.6f}"
                )
                time.sleep(args.interval)
                continue

            saved = api_request(
                f"{args.api}/walks/{walk_id}/points",
                method="POST",
                payload=point,
                user_id=args.user,
            )
            print(
                f"Point {saved['id']}: "
                f"{saved['latitude']:.6f}, {saved['longitude']:.6f}"
            )
            time.sleep(args.interval)

        if queued_points:
            result = api_request(
                f"{args.api}/walks/{walk_id}/points/batch",
                method="POST",
                payload={"points": queued_points},
                user_id=args.user,
            )
            print(
                f"Uploaded {result['created_count']} queued points "
                f"({result['duplicate_count']} already stored)"
            )

        print(f"Open {args.api}/app/ to see the trail.")
    except (HTTPError, URLError) as error:
        raise SystemExit(f"TrailBuddy API request failed: {error}") from error


if __name__ == "__main__":
    main()
