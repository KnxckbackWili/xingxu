"""PostgreSQL gate for retained project/issue locks, CAS versions and audit writes.

Uses real application update handlers in separate sessions. The explicitly named
CI/test database is disposable; this script rebuilds its schema through Alembic.
"""

import os
import re
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from uuid import uuid4

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="pg-gate-")
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["AGVPM_ENABLE_CACHE"] = "0"
os.environ["SEED_DEMO_USERS"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlalchemy import MetaData, text
from sqlalchemy.engine import make_url
from app.db import SessionLocal, engine, _alembic_sync_schema
from app.models import Project, User, Issue, ChangeLog
from app.routers.projects import ProjectUpdate, update_project
from app.routers.issues import IssueUpdate, update_issue

url = make_url(os.environ.get("DATABASE_URL", ""))
if url.get_backend_name() != "postgresql" or not re.search(
    r"(?:^|_)(?:ci|test|tests|pytest|gate|gates)(?:_|$)", url.database or "", re.I
):
    raise SystemExit(
        "pg_gate requires DATABASE_URL for a disposable PostgreSQL CI/test/gate database"
    )

physical = MetaData()
physical.reflect(bind=engine)
physical.drop_all(bind=engine)
_alembic_sync_schema()
with SessionLocal() as db:
    db.add(
        User(
            id="gate-admin",
            username="gate-admin",
            password_hash="not-a-login-hash",
            display_name="门禁管理员",
            role="admin",
        )
    )
    db.commit()

failures = []


def check(label, condition, detail=""):
    print(
        ("PASS " if condition else "FAIL ") + label + (": " + detail if detail else ""),
        flush=True,
    )
    if not condition:
        failures.append(label)


def project(label):
    with SessionLocal() as db:
        item = Project(
            name=label,
            client="Original",
            manager="gate-admin",
            created_by="gate-admin",
            status="executing",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        db.add(item)
        db.commit()
        return item.id


def state(pid):
    with SessionLocal() as db:
        row = db.get(Project, pid)
        return row.version, row.client


def audit_count(pid, entity_type):
    with SessionLocal() as db:
        return (
            db.query(ChangeLog)
            .filter_by(project_id=pid, entity_type=entity_type, action="update")
            .count()
        )


def edit_project(pid, value, version=0, actor="gate-admin"):
    def call(db):
        # Populate stale identity-map state before the common project lock.
        user = db.get(User, actor)
        db.get(Project, pid)
        return update_project(
            pid, ProjectUpdate(client=value, version=version), user=user, db=db
        )

    return call


def run(body):
    with SessionLocal() as db:
        try:
            body(db)
            return "ok", None
        except HTTPException as error:
            return "http", error.status_code
        except Exception as error:
            return "error", type(error).__name__
        finally:
            db.rollback()


def race(bodies):
    barrier = threading.Barrier(len(bodies))
    results = [None] * len(bodies)

    def worker(index):
        barrier.wait(timeout=10)
        results[index] = run(bodies[index])

    threads = [
        threading.Thread(target=worker, args=(index,), daemon=True)
        for index in range(len(bodies))
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 20
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))
    return results


print("S0: real PostgreSQL project row lock blocks the application writer", flush=True)
pid = project("S0")
with SessionLocal() as holder:
    holder.execute(
        text("SELECT id FROM projects WHERE id=:id FOR UPDATE"), {"id": pid}
    ).all()
    result = []
    started = time.monotonic()
    writer = threading.Thread(
        target=lambda: result.append(run(edit_project(pid, "After lock"))), daemon=True
    )
    writer.start()
    time.sleep(0.5)
    check("S0 writer waits while row is locked", writer.is_alive() and not result)
    holder.rollback()
    writer.join(timeout=15)
check("S0 writer succeeds after lock release", result == [("ok", None)])
check("S0 lock wait measured >=400ms", (time.monotonic() - started) * 1000 >= 400)
check(
    "S0 version/client/audit commit together",
    state(pid) == (1, "After lock") and audit_count(pid, "project") == 1,
)

print("S1: two writers carrying the same project version", flush=True)
pid = project("S1")
results = race([edit_project(pid, "First"), edit_project(pid, "Second")])
check(
    "S1 exactly one success and one conflict",
    results.count(("ok", None)) == 1 and results.count(("http", 409)) == 1,
    str(results),
)
check(
    "S1 version increments once, winning value retained",
    state(pid)[0] == 1 and state(pid)[1] in {"First", "Second"},
)
check("S1 one update audit", audit_count(pid, "project") == 1)

print("S2: eight competing project updates", flush=True)
pid = project("S2")
results = race([edit_project(pid, f"Writer {index}") for index in range(8)])
check(
    "S2 one success and seven 409s",
    results.count(("ok", None)) == 1 and results.count(("http", 409)) == 7,
    str(results),
)
check(
    "S2 one version and one audit",
    state(pid)[0] == 1 and audit_count(pid, "project") == 1,
)
before = state(pid)
check(
    "S2 stale retry is rejected", run(edit_project(pid, "Stale retry")) == ("http", 409)
)
check(
    "S2 stale retry cannot overwrite or add audit",
    state(pid) == before and audit_count(pid, "project") == 1,
)

print(
    "S3: retained issue update follows the common project lock and issue CAS",
    flush=True,
)
pid = project("S3")
with SessionLocal() as db:
    issue = Issue(project_id=pid, title="Original issue", reporter_id="gate-admin")
    db.add(issue)
    db.commit()
    issue_id = issue.id


def edit_issue(index):
    def call(db):
        return update_issue(
            issue_id,
            IssueUpdate(title=f"Issue writer {index}", version=0),
            user=db.get(User, "gate-admin"),
            db=db,
        )

    return call


results = race([edit_issue(index) for index in range(8)])
check(
    "S3 one issue success and seven conflicts",
    results.count(("ok", None)) == 1 and results.count(("http", 409)) == 7,
    str(results),
)
with SessionLocal() as db:
    issue = db.get(Issue, issue_id)
    check(
        "S3 issue version increments once",
        issue.version == 1 and issue.title.startswith("Issue writer "),
    )
check("S3 one issue audit", audit_count(pid, "issue") == 1)

print("S4: account disabled while its update waits for the project lock", flush=True)
pid = project("S4")
with SessionLocal() as holder:
    holder.execute(
        text("SELECT id FROM projects WHERE id=:id FOR UPDATE"), {"id": pid}
    ).all()
    result = []
    writer = threading.Thread(
        target=lambda: result.append(run(edit_project(pid, "Must not commit"))),
        daemon=True,
    )
    writer.start()
    time.sleep(0.3)
    holder.execute(text("UPDATE users SET is_active=FALSE WHERE id='gate-admin'"))
    holder.commit()
    writer.join(timeout=15)
check("S4 refreshed inactive actor is rejected", result == [("http", 401)], str(result))
check(
    "S4 project and audit remain unchanged",
    state(pid) == (0, "Original") and audit_count(pid, "project") == 0,
)
with SessionLocal() as db:
    db.execute(text("UPDATE users SET is_active=TRUE WHERE id='gate-admin'"))
    db.commit()

print("S5: audit failure rolls back the project edit and its version", flush=True)
import app.routers.projects as project_routes

pid = project("S5")
original_log = project_routes.log_change


def reject_audit(*args, **kwargs):
    raise RuntimeError("synthetic gate audit failure")


project_routes.log_change = reject_audit
try:
    result = run(edit_project(pid, "Must roll back"))
finally:
    project_routes.log_change = original_log
check("S5 handler reports audit failure", result == ("error", "RuntimeError"))
check(
    "S5 neither version nor field was committed",
    state(pid) == (0, "Original") and audit_count(pid, "project") == 0,
)

if failures:
    raise SystemExit("PostgreSQL gate failed: " + ", ".join(failures))
print("PostgreSQL retained project/issue row-lock gate: all checks passed", flush=True)
