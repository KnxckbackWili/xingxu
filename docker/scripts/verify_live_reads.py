"""Read-only deployment checks against real data in the running container.

Run from the repository root:
    docker exec -i agv-pm-7001 python - < docker/scripts/verify_live_reads.py

Reads every parameter-free GET page and every per-project GET page of the
running application as an active administrator and an active employee. The
route list comes from the application itself, so it follows the current
version. This does not replace browser interaction or isolated write-flow
tests. Tokens stay in memory and are sent only to the same container's
loopback HTTP server.
"""

import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if sys.platform != "linux" or not Path("/.dockerenv").is_file():
    raise SystemExit("Run with docker exec inside the serving container; never open its live SQLite from the host.")

from app.db import SessionLocal
from app.deps import create_token
from app.main import app
from app.models import User

# Downloads, streams and one-time flows are not page reads.
SKIP = re.compile(r"/(export|download|stream|events|file|files|blank|preview|login|logout|refresh|mfa)(/|$|\?)")

with SessionLocal() as db:
    identities = []
    for role in ("admin", "employee"):
        user = db.query(User).filter(User.is_active.is_(True), User.role == role).order_by(User.created_at).first()
        if user is not None:
            identities.append((role, create_token(user)))
if not identities:
    raise SystemExit("No active account: checks could not run.")

plain, per_project = [], []
for route in app.routes:
    path = getattr(route, "path", "")
    if "GET" not in getattr(route, "methods", set()) or not path.startswith("/api/") or SKIP.search(path):
        continue
    params = re.findall(r"{([^}]+)}", path)
    if not params:
        plain.append(path[4:])
    elif params == ["project_id"]:
        per_project.append(path[4:])

failures = []
total = 0
for role, token in identities:
    def read(path):
        request = Request("http://127.0.0.1:8000/api" + path, headers={"Authorization": "Bearer " + token})
        try:
            with urlopen(request, timeout=20) as response:
                return path, response.status, json.load(response)
        except HTTPError as error:
            return path, error.code, None
        except (URLError, TimeoutError, ValueError, OSError):
            return path, 0, None

    projects = read("/projects")
    if projects[1] != 200 or not isinstance(projects[2], list):
        failures.append({"role": role, "path": "/projects", "status": projects[1]})
        continue
    paths = list(plain)
    for project in projects[2]:
        paths.extend(path.replace("{project_id}", project["id"]) for path in per_project)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read, paths))
    total += len(results)
    for path, status, _ in results:
        # 403 is an honest answer for an employee on an administrator page; 5xx and timeouts are not.
        if status == 0 or status >= 500 or (role == "admin" and status == 403):
            failures.append({"role": role, "path": path, "status": status})
    print(json.dumps({"role": role, "page_reads": len(results), "statuses": dict(Counter(result[1] for result in results))}))

print(json.dumps({"total_reads": total, "failures": failures}, ensure_ascii=False))
if failures:
    raise SystemExit(1)
