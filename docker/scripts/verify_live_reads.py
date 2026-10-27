"""Read-only deployment checks against real data in the running container.

Run from the repository root:
    docker exec -i agv-pm-7001 python - < docker/scripts/verify_live_reads.py

Checks admin/PM page reads and repeated non-empty governance reads. This does
not replace browser interaction or isolated write-flow tests. Tokens stay in
memory and are sent only to the same container's loopback HTTP server.
"""

import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if sys.platform != "linux" or not Path("/.dockerenv").is_file():
    raise SystemExit("Run with docker exec inside the serving container; never open its live SQLite from the host.")

from app.db import SessionLocal
from app.deps import create_token
from app.models import User

with SessionLocal() as db:
    identities = [
        (user.role, create_token(user))
        for user in db.query(User).filter(User.is_active.is_(True), User.role.in_(["admin", "pm"]))
    ]
if not identities:
    raise SystemExit("No active admin/PM identity: checks could not run.")

monday = date.today() - timedelta(days=date.today().weekday())
week = f"from_date={monday}&to_date={monday + timedelta(days=6)}"
failures = []
total = 0
nonempty_governance = False

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

    def record(result, expected=200):
        global total
        total += 1
        path, status, body = result
        if status != expected:
            failures.append({"role": role, "path": path, "status": status, "expected": expected})
        return body

    projects = record(read("/projects"))
    if not isinstance(projects, list):
        failures.append({"role": role, "path": "/projects", "error": "Expected a project list"})
        continue
    paths = [
        "/projects/governance/requests", "/dashboard/overview", "/dashboard/overdue",
        "/dashboard/people-summary", "/dashboard/people-overview",
        "/dashboard/people-plan?" + week, "/dashboard/staffing?" + week,
        "/dashboard/stats", "/dashboard/metrics", "/dashboard/issues", "/inventory",
        "/templates", "/templates/default/tree", "/vehicle-types", "/org/groups",
        "/notifications?limit=20", "/notifications/unread-count", "/users/all-active", "/feedback",
    ]
    if role == "admin":
        paths.extend(["/users", "/system/backups"])
    # Role configuration is intentionally unavailable to a PM.
    record(read("/org/roles"), expected=200 if role == "admin" else 403)
    for project in projects:
        base = "/projects/" + project["id"]
        paths.extend(base + suffix for suffix in [
            "", "/overview", "/progress", "/progress/timeline", "/tree", "/modules",
            "/schedule", "/preparations", "/preparations/reviews", "/overdue",
            "/current-phase", "/issues", "/incidents", "/logs", "/report",
            "/archive-checklist", "/acceptance", "/vehicles", "/vehicle-units",
            "/inventory", "/attachments", "/handover-summary", "/item-applications",
        ])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(read, paths))
    for result in results:
        body = record(result)
        path, status, _ = result
        if path == "/projects/governance/requests" and status == 200:
            if not isinstance(body, list):
                failures.append({"role": role, "path": path, "error": "Expected an application list"})
            elif body:
                nonempty_governance = True
                # Exercise pooled connections; an isolated successful read missed this incident.
                with ThreadPoolExecutor(max_workers=6) as pool:
                    for repeated in pool.map(read, [path] * 60):
                        repeated_body = record(repeated)
                        if not isinstance(repeated_body, list) or not repeated_body:
                            failures.append({"role": role, "path": path, "error": "Repeated read returned no application data"})
        if path.endswith("/tree") and "/projects/" in path and status == 200:
            tasks = [task for phase in body for module in phase.get("modules", []) for task in module.get("tasks", [])]
            if tasks:
                record(read(path[:-5] + "/tasks/" + tasks[0]["id"] + "/workspace"))
    print(json.dumps({"role": role, "page_reads": len(results), "statuses": dict(Counter(result[1] for result in results))}))

print(json.dumps({"total_reads": total, "nonempty_governance_exercised": nonempty_governance, "failures": failures}))
if failures:
    raise SystemExit(1)
if not nonempty_governance:
    raise SystemExit("Empty application lists: page reads passed, but the incident regression was NOT exercised. Test an isolated restored copy with application data.")
