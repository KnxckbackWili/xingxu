"""State transitions must recheck the actor after waiting for the project lock."""
from unittest.mock import patch

import pytest


def _create(client, headers):
    result = client.post("/api/projects", headers=headers, json={
        "name": "状态权限并发验收", "start_date": "2026-10-01", "end_date": "2026-12-31",
    })
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize("change,expected_status", [("permissions", 403), ("disabled", 401)])
def test_status_rechecks_actor_after_waiting_for_project_lock(client, pm_headers, admin_headers,
                                                            change, expected_status):
    from app.db import SessionLocal
    from app.models import User
    from app.services.record_lock import lock_record

    project = _create(client, pm_headers)
    project_url = f"/api/projects/{project['id']}"
    before = client.get(project_url, headers=admin_headers).json()
    before_logs = client.get(f"{project_url}/logs", headers=admin_headers).json()

    def change_actor_before_lock(db, row, **kwargs):
        # A separate committed transaction represents the administrator's
        # change while this request waits; the request's identity map stays old.
        with SessionLocal() as other:
            actor = other.query(User).filter_by(username="pm").one()
            if change == "permissions":
                actor.permission_overrides = {"project.update": False, "project.archive": False}
                actor.permission_version += 1
            else:
                actor.is_active = False
            other.commit()
        return lock_record(db, row, **kwargs)

    with patch("app.services.record_lock.lock_record", side_effect=change_actor_before_lock):
        result = client.post(f"{project_url}/status", headers=pm_headers, json={"status": "preparing"})

    assert result.status_code == expected_status, result.text
    assert client.get(project_url, headers=admin_headers).json() == before
    assert client.get(f"{project_url}/logs", headers=admin_headers).json() == before_logs


def test_archive_explicit_deny_is_rechecked_after_waiting_for_lock(client, pm_headers, admin_headers):
    from app.db import SessionLocal
    from app.models import Project, User
    from app.services.record_lock import lock_record

    project = _create(client, pm_headers)
    # Existing completed data is a fixture; the denied request must never reach
    # or bypass any completion, checklist or archive evidence gate.
    with SessionLocal() as db:
        db.get(Project, project["id"]).status = "completed"
        db.commit()
    project_url = f"/api/projects/{project['id']}"
    before = client.get(project_url, headers=admin_headers).json()
    before_logs = client.get(f"{project_url}/logs", headers=admin_headers).json()

    def deny_archive_before_lock(db, row, **kwargs):
        with SessionLocal() as other:
            actor = other.query(User).filter_by(username="pm").one()
            actor.permission_overrides = {"project.archive": False}
            actor.permission_version += 1
            other.commit()
        return lock_record(db, row, **kwargs)

    with patch("app.services.record_lock.lock_record", side_effect=deny_archive_before_lock):
        result = client.post(f"{project_url}/status", headers=pm_headers,
                             json={"status": "archived", "retrospective": "不得写入的复盘"})

    assert result.status_code == 403, result.text
    assert client.get(project_url, headers=admin_headers).json() == before
    assert client.get(f"{project_url}/logs", headers=admin_headers).json() == before_logs


def test_archive_deny_keeps_other_authorized_status_changes_available(client, pm_headers):
    from app.db import SessionLocal
    from app.models import User

    project = _create(client, pm_headers)
    with SessionLocal() as db:
        actor = db.query(User).filter_by(username="pm").one()
        actor.permission_overrides = {"project.archive": False}
        actor.permission_version += 1
        db.commit()

    result = client.post(f"/api/projects/{project['id']}/status", headers=pm_headers,
                         json={"status": "preparing"})
    assert result.status_code == 200, result.text
    current = client.get(f"/api/projects/{project['id']}", headers=pm_headers).json()
    assert current["status"] == "preparing" and current["version"] == project["version"] + 1
