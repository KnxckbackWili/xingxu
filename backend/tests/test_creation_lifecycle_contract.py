"""New project defaults and explicit human lifecycle decisions."""
import pytest


def create_body(**fields):
    return {
        "name": "草稿生命周期契约", "start_date": "2026-10-05",
        "end_date": "2026-11-30", "new_vehicles": False, **fields,
    }


def test_omitted_create_status_stays_draft_after_readback(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body())
    assert created.status_code == 200
    assert created.json()['status'] == 'draft'
    pid = created.json()['id']
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'draft'
    assert client.get(f'/api/projects/{pid}/schedule', headers=pm_headers).json() == []


def test_new_draft_cannot_skip_preparation_or_entry_review(client, pm_headers):
    from tests.lifecycle_helpers import approve_risk_entry
    created = client.post('/api/projects', headers=pm_headers, json=create_body())
    assert created.status_code == 200
    pid = created.json()['id']
    assert created.json()['status'] == 'draft'
    for target in ['ready', 'executing']:
        rejected = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': target})
        assert rejected.status_code == 400
        assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'draft'
    for target in ['preparing', 'planning', 'ready']:
        changed = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': target})
        assert changed.status_code == 200, changed.text
    rejected = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'executing'})
    assert rejected.status_code == 400
    assert '进场' in rejected.text
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'ready'
    approve_risk_entry(client, pm_headers, pid)
    for target in ['executing', 'commissioning', 'pilot', 'acceptance']:
        changed = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': target})
        assert changed.status_code == 200, changed.text
    rejected = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'completed'})
    assert rejected.status_code == 400
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'acceptance'


@pytest.mark.parametrize('status', ['preparing', 'planning', 'ready'])
def test_explicit_legacy_initial_state_is_not_silently_rewritten(client, pm_headers, status):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(status=status))
    assert created.status_code == 200
    assert created.json()['status'] == status


def test_worker_cannot_create_project_or_gain_stage_management(client, worker_headers, pm_headers):
    assert client.post('/api/projects', headers=worker_headers, json=create_body()).status_code == 403
    pid = client.post('/api/projects', headers=pm_headers, json=create_body()).json()['id']
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json={'members': [uid]}).status_code == 200
    assert client.post(f'/api/projects/{pid}/status', headers=worker_headers, json={'status': 'preparing'}).status_code == 403
    assert client.get(f'/api/projects/{pid}', headers=worker_headers).json()['status'] == 'draft'


def test_template_creation_generates_content_without_starting_the_project(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(
        vehicles=[{'vehicle_type': '潜伏式', 'model_name': 'QA', 'quantity': 2}],
        template_id='default', module_ids=['mod-01'],
    ))
    assert created.status_code == 200, created.text
    assert created.json()['status'] == 'draft'
    assert created.json()['initial_generation']['tasks'] > 0
    detail = client.get(f"/api/projects/{created.json()['id']}", headers=pm_headers).json()
    assert detail['status'] == 'draft'
    assert detail['vehicle_total'] == 2
    assert detail['schedule_summary'] == {'total': 0, 'confirmed': 0}


def test_import_missing_status_and_clone_both_start_fresh_drafts(client, pm_headers):
    source = client.post('/api/projects', headers=pm_headers, json=create_body(status='preparing')).json()
    payload = client.get(f"/api/projects/{source['id']}/export/json", headers=pm_headers).json()
    payload['project'].pop('status')
    preview = client.post('/api/projects/import/preview', headers=pm_headers, json=payload)
    assert preview.status_code == 200 and preview.json()['valid']
    imported = client.post('/api/projects/import/json', headers=pm_headers, json=payload)
    assert imported.status_code == 200, imported.text
    assert client.get(f"/api/projects/{imported.json()['id']}", headers=pm_headers).json()['status'] == 'draft'
    cloned = client.post(f"/api/projects/{source['id']}/clone", headers=pm_headers, json={'name': '新草稿克隆'})
    assert cloned.status_code == 200, cloned.text
    detail = client.get(f"/api/projects/{cloned.json()['id']}", headers=pm_headers).json()
    assert detail['status'] == 'draft'
    assert detail['schedule_summary'] == {'total': 0, 'confirmed': 0}
    assert client.get(f"/api/projects/{source['id']}", headers=pm_headers).json()['status'] == 'preparing'
