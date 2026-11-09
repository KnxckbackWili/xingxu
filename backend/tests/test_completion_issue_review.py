"""Completion uses business invariants; archived issue ledgers remain immutable."""
from tests.lifecycle_helpers import versioned
from datetime import date
import pytest
from tests.template_work import default_work


def project(client, headers):
    response = client.post('/api/projects', headers=headers, json={
        'name': 'Workflow regression', 'start_date': '2026-09-01', 'end_date': '2026-10-01', 'new_vehicles': False,
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


@pytest.mark.parametrize('operation', ['create', 'import', 'update', 'reopen', 'delete'])
def test_archived_issue_mutations_rejected(client, pm_headers, operation):
    from app.db import SessionLocal
    from app.models import Project
    pid = project(client, pm_headers)
    issue = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': 'Issue'}).json()
    client.put(f"/api/issues/{issue['id']}", headers=pm_headers, json=versioned(issue['id'], {'status': 'resolved'}, 'Issue'))
    with SessionLocal() as db:
        db.get(Project, pid).status = 'archived'
        db.commit()
    path = f"/api/issues/{issue['id']}"
    if operation == 'create':
        result = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': 'late'})
    elif operation == 'import':
        result = client.post(f'/api/projects/{pid}/issues/import', headers=pm_headers, json={'items': [{'title': 'late'}]})
    elif operation == 'update':
        result = client.put(path, headers=pm_headers, json=versioned(issue['id'], {'title': 'changed'}, 'Issue'))
    elif operation == 'reopen':
        result = client.post(path + '/reopen', headers=pm_headers)
    else:
        result = client.delete(path, headers=pm_headers)
    assert result.status_code == 400, result.text
    assert '归档' in result.json()['detail']
    rows = client.get(f'/api/projects/{pid}/issues', headers=pm_headers).json()
    assert len(rows) == 1 and rows[0]['title'] == 'Issue' and rows[0]['status'] == 'resolved'


def test_worker_can_find_resolved_issues_for_reopen(client, pm_headers, worker_headers):
    pid = project(client, pm_headers)
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    issue = client.post(f'/api/projects/{pid}/issues', headers=worker_headers, json={'title': 'Verify fix'}).json()
    assert client.put(f"/api/issues/{issue['id']}", headers=pm_headers, json=versioned(issue['id'], {'status': 'resolved'}, 'Issue')).status_code == 200
    assert not client.get('/api/dashboard/issues', headers=worker_headers).json()['items']
    rows = client.get('/api/dashboard/issues?include_closed=true', headers=worker_headers).json()['items']
    assert rows[0]['id'] == issue['id'] and rows[0]['project_status'] == 'preparing'
    assert client.post(f"/api/issues/{issue['id']}/reopen", headers=worker_headers).status_code == 200

