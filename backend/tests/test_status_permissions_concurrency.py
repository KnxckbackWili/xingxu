"""State transitions must recheck the actor after waiting for the project lock."""
from unittest.mock import patch

import pytest


def _create(client, headers):
    result = client.post("/api/projects", headers=headers, json={
        "name": "状态权限并发验收", "start_date": "2026-10-01", "end_date": "2026-12-31",
    })
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize("change,expected_status", [("disabled", 401)])
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
            actor.is_active = False
            other.commit()
        return lock_record(db, row, **kwargs)

    with patch("app.services.record_lock.lock_record", side_effect=change_actor_before_lock):
        result = client.post(f"{project_url}/status", headers=pm_headers, json={"status": "preparing"})

    assert result.status_code == expected_status, result.text
    assert client.get(project_url, headers=admin_headers).json() == before
    assert client.get(f"{project_url}/logs", headers=admin_headers).json() == before_logs

