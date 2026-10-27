"""Completion uses business invariants; archived issue ledgers remain immutable."""
from tests.lifecycle_helpers import versioned
from datetime import date
import pytest


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
        result = client.put(path, headers=pm_headers, json={'title': 'changed'})
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
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [uid]})).status_code == 200
    issue = client.post(f'/api/projects/{pid}/issues', headers=worker_headers, json={'title': 'Verify fix'}).json()
    assert client.put(f"/api/issues/{issue['id']}", headers=pm_headers, json=versioned(issue['id'], {'status': 'resolved'}, 'Issue')).status_code == 200
    assert not client.get('/api/dashboard/issues', headers=worker_headers).json()['items']
    rows = client.get('/api/dashboard/issues?include_closed=true', headers=worker_headers).json()['items']
    assert rows[0]['id'] == issue['id'] and rows[0]['project_status'] == 'draft'
    assert client.post(f"/api/issues/{issue['id']}/reopen", headers=worker_headers).status_code == 200


def test_document_submitter_cannot_be_forged_to_self_approve(client, pm_headers, worker_headers):
    from tests.document_helpers import documents, upload_documents
    pid = project(client, pm_headers)
    pm = client.get('/api/auth/me', headers=pm_headers).json()['id']
    worker = client.get('/api/auth/me', headers=worker_headers).json()['id']
    row = documents(client, pm_headers, pid)['documents'][0]
    submitted = upload_documents(client, pm_headers, pid, [row['id']], submitted_by=worker, uploaded_by=worker)['documents'][0]
    version = submitted['versions'][0]
    assert version['uploaded_by'] == pm
    response = client.post(f'/api/projects/{pid}/documents/{row["id"]}/versions/{version["id"]}/review', headers=pm_headers, json={'decision': 'approved'})
    assert response.status_code == 400 and '不能自己审核' in response.json()['detail']


def test_vehicle_notes_edit_preserves_manual_target(client, pm_headers):
    from app.db import SessionLocal
    from app.models import Task
    pid = project(client, pm_headers)
    vehicle = client.post(f'/api/projects/{pid}/vehicles', headers=pm_headers, json={
        'vehicle_type': '潜伏式', 'model_name': 'A', 'quantity': 2,
    }).json()
    assert client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': ['mod-03']}).status_code == 200
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=pid, quantity_type='per_vehicle').first()
        task.target_quantity = 17
        db.commit(); tid = task.id
    path = f"/api/projects/{pid}/vehicles/{vehicle['id']}"
    assert client.put(path, headers=pm_headers, json={'notes': 'updated', 'quantity': 2}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Task, tid).target_quantity == 17
    assert client.put(path, headers=pm_headers, json={'quantity': 3}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Task, tid).target_quantity == 3


def test_document_review_is_metadata_and_does_not_erase_submitted_file(client, pm_headers, worker_headers):
    from tests.document_helpers import documents, upload_documents
    pid = project(client, pm_headers)
    worker = client.get('/api/auth/me', headers=worker_headers).json()['id']
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [worker]})).status_code == 200
    row = documents(client, pm_headers, pid)['documents'][0]
    submitted = upload_documents(client, worker_headers, pid, [row['id']])['documents'][0]
    version = submitted['versions'][0]
    response = client.post(f'/api/projects/{pid}/documents/{row["id"]}/versions/{version["id"]}/review', headers=pm_headers, json={'decision': 'rejected', 'note': '补充复测记录'})
    assert response.status_code == 200, response.text
    kept = next(value for value in documents(client, pm_headers, pid)['documents'] if value['id'] == row['id'])
    assert kept['status'] == 'submitted' and kept['versions'][0]['uploaded_by'] == worker
    assert kept['versions'][0]['review_metadata']['latest_review']['decision'] == 'rejected'
