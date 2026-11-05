"""Selecting execution work is the single input for its preparation checklist."""
from app.db import SessionLocal
from app.models import Module, Task, Project
from tests.template_work import default_work


def create(client, headers, **scope):
    result = client.post('/api/projects', headers=headers, json={
        'name': '范围与准备联动', 'start_date': '2026-09-16', 'end_date': '2026-12-31',
        'new_vehicles': False, **scope})
    assert result.status_code == 200, result.text
    return result.json()['id']


def names(client, headers, pid):
    state = client.get(f'/api/projects/{pid}/documents', headers=headers).json()
    return {item['name'] for item in state['definitions'] if item['stage_key'] != 'legacy'}


def test_later_added_work_preserves_project_document_identity_and_evidence(client, pm_headers):
    from tests.document_helpers import documents, upload_documents
    pid = create(client, pm_headers, work_item_ids=default_work('mod-03'))
    before = documents(client, pm_headers, pid)
    row = before['documents'][0]
    submitted = upload_documents(client, pm_headers, pid, [row['id']])['documents'][0]
    path = f'/api/projects/{pid}/tasks/generate'
    for _ in range(2):
        assert client.post(path, headers=pm_headers, json={'work_item_ids': default_work('mod-15')}).status_code == 200
    after = documents(client, pm_headers, pid)
    assert {row['id'] for row in after['definitions']} == {row['id'] for row in before['definitions']}
    kept = next(item for item in after['documents'] if item['id'] == row['id'])
    assert kept['status'] == 'submitted' and kept['versions'] == submitted['versions']
    assert client.get(f'/api/projects/{pid}/procurements', headers=pm_headers).json()['items'] == []


