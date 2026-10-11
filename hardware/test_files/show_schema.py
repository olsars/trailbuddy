import sys, json
d = json.load(sys.stdin)
routes = [("/walks/start", "post"), ("/walks/{walk_id}", "patch"),
          ("/walks/{walk_id}/points/batch", "post")]
for path, method in routes:
    op = d["paths"][path][method]
    print("=====", method.upper(), path)
    print("params:", [(p["name"], p["in"]) for p in op.get("parameters", [])])
    ref = (op.get("requestBody", {}).get("content", {})
           .get("application/json", {}).get("schema", {}).get("$ref"))
    if ref:
        print(json.dumps(d["components"]["schemas"][ref.split("/")[-1]], indent=1))
    if method == "post" and path == "/walks/start":
        print("responses:", json.dumps(op["responses"], indent=1))