"""New project defaults and explicit human lifecycle decisions (v3: every project starts in preparing)."""
from tests.lifecycle_helpers import versioned
import pytest
from tests.template_work import default_work


def create_body(**fields):
    return {
        "name": "准备生命周期契约", "start_date": "2026-10-05",
        "end_date": "2026-11-30", "new_vehicles": False, **fields,
    }


def _status(client, headers, pid):
    return client.get(f'/api/projects/{pid}', headers=headers).json()['status']


def test_omitted_create_status_starts_preparing_after_readback(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body())
    assert created.status_code == 200
    assert created.json()['status'] == 'preparing'
    assert _status(client, pm_headers, created.json()['id']) == 'preparing'


@pytest.mark.parametrize('status', ['ready', 'executing', 'planning', 'draft'])
def test_explicit_non_preparing_initial_state_is_rejected(client, pm_headers, status):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(status=status))
    assert created.status_code == 400
    assert '准备' in created.json()['detail']


def test_explicit_preparing_initial_state_is_accepted(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(status='preparing'))
    assert created.status_code == 200 and created.json()['status'] == 'preparing'


def test_every_employee_can_create_a_project_and_record_its_status(client, worker_headers, pm_headers):
    assert client.post('/api/projects', headers=worker_headers, json=create_body()).status_code == 200
    pid = client.post('/api/projects', headers=pm_headers, json=create_body()).json()['id']
    assert client.post(f'/api/projects/{pid}/status', headers=worker_headers, json={'status': 'executing'}).status_code == 200
    assert _status(client, worker_headers, pid) == 'executing'


def test_template_creation_generates_content_without_starting_the_project(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json=create_body(
        vehicles=[{'vehicle_type': '潜伏式', 'model_name': 'QA', 'quantity': 2}],
        template_id='default', work_item_ids=default_work('mod-01'),
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
