"""Quantity reporting, quality verification and issue handling stay distinct."""
from tests.lifecycle_helpers import versioned
from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Project, Phase, Module, Task, CheckItem
from app.services.progress import project_completion_blockers, task_progress
from tests.test_completion_issue_review import project

def test_completed_issue_reopen_keeps_state_and_notifies_manager(client, pm_headers, worker_headers):
    from app.models import Notification, Issue
    pid = project(client, pm_headers)
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    issue = client.post(f'/api/projects/{pid}/issues', headers=worker_headers, json={'title': '复发'}).json()
    client.put(f"/api/issues/{issue['id']}", headers=pm_headers, json=versioned(issue['id'], {'status': 'resolved'}, 'Issue'))
    with SessionLocal() as db:
        db.get(Project, pid).status = 'completed'; old_version = db.get(Issue, issue['id']).version; db.commit()
    result = client.post(f"/api/issues/{issue['id']}/reopen", headers=worker_headers)
    assert result.status_code == 200
    with SessionLocal() as db:
        assert db.get(Project, pid).status == 'completed'
        assert db.get(Issue, issue['id']).version == old_version + 1
        assert any('恢复到验收中' in (n.content or '') for n in db.query(Notification).filter_by(project_id=pid).all())
