"""New project defaults and explicit human lifecycle decisions (v3: every project starts in preparing)."""
from tests.lifecycle_helpers import versioned
import pytest


def create_body(**fields):
    return {
        "name": "筹备生命周期契约", "start_date": "2026-10-05",
        "end_date": "2026-11-30", "new_vehicles": False, **fields,
    }


def _status(client, headers, pid):
    return client.get(f'/api/projects/{pid}', headers=headers).json()['status']


def test_omitted_create_status_starts_preparing_after_readback(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body())
    assert created.status_code == 200
    assert created.json()['status'] == 'preparing'
    assert _status(client, pm_headers, created.json()['id']) == 'preparing'


def test_new_project_cannot_skip_kickoff_documents_or_entry_review(client, pm_headers):
    from tests.lifecycle_helpers import approve_risk_entry
    from tests.document_helpers import documents, upload_documents
    pid = client.post('/api/projects', headers=pm_headers, json=create_body()).json()['id']
    for target in ['ready', 'executing']:
        rejected = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': target})
        assert rejected.status_code == 400
        assert _status(client, pm_headers, pid) == 'preparing'
    kickoff = [row['id'] for row in documents(client, pm_headers, pid)['documents'] if row['stage_key'] == '4' and row['required']]
    upload_documents(client, pm_headers, pid, kickoff)
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'ready'}).status_code == 200
    rejected = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'executing'})
    assert rejected.status_code == 400
    assert '发车前' in rejected.text
    assert _status(client, pm_headers, pid) == 'ready'
    approve_risk_entry(client, pm_headers, pid)
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'executing'}).status_code == 200
    # Signoff documents gate acceptance; completion needs the acceptance gate.
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'acceptance'}).status_code == 400
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'completed'}).status_code == 400
    assert _status(client, pm_headers, pid) == 'executing'


@pytest.mark.parametrize('status', ['ready', 'executing', 'planning', 'draft'])
def test_explicit_non_preparing_initial_state_is_rejected(client, pm_headers, status):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(status=status))
    assert created.status_code == 400
    assert '筹备' in created.json()['detail']


def test_explicit_preparing_initial_state_is_accepted(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(status='preparing'))
    assert created.status_code == 200 and created.json()['status'] == 'preparing'


def test_worker_cannot_create_project_or_gain_stage_management(client, worker_headers, pm_headers):
    assert client.post('/api/projects', headers=worker_headers, json=create_body()).status_code == 403
    pid = client.post('/api/projects', headers=pm_headers, json=create_body()).json()['id']
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [uid]})).status_code == 200
    assert client.post(f'/api/projects/{pid}/status', headers=worker_headers, json={'status': 'ready'}).status_code == 403
    assert _status(client, worker_headers, pid) == 'preparing'


def test_template_creation_generates_content_without_starting_the_project(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(
        vehicles=[{'vehicle_type': '潜伏式', 'model_name': 'QA', 'quantity': 2}],
        template_id='default', module_ids=['mod-01'],
    ))
    assert created.status_code == 200, created.text
    assert created.json()['status'] == 'preparing'
    assert created.json()['initial_generation']['tasks'] > 0
    detail = client.get(f"/api/projects/{created.json()['id']}", headers=pm_headers).json()
    assert detail['status'] == 'preparing'
    assert detail['vehicle_total'] == 2


def test_import_missing_status_and_clone_both_start_preparing(client, pm_headers):
    from tests.lifecycle_helpers import enter_execution
    source = client.post('/api/projects', headers=pm_headers, json=create_body()).json()
    enter_execution(client, pm_headers, source['id'])
    payload = client.get(f"/api/projects/{source['id']}/export/json", headers=pm_headers).json()
    payload['project'].pop('status')
    preview = client.post('/api/projects/import/preview', headers=pm_headers, json=payload)
    assert preview.status_code == 200 and preview.json()['valid']
    imported = client.post('/api/projects/import/json', headers=pm_headers, json=payload)
    assert imported.status_code == 200, imported.text
    assert _status(client, pm_headers, imported.json()['id']) == 'preparing'
    cloned = client.post(f"/api/projects/{source['id']}/clone", headers=pm_headers, json={'name': '新筹备克隆'})
    assert cloned.status_code == 200, cloned.text
    assert _status(client, pm_headers, cloned.json()['id']) == 'preparing'
    assert _status(client, pm_headers, source['id']) == 'executing'
