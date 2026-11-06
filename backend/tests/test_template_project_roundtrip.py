"""模板、项目及旧资料来源的便携往返。"""

from tests.lifecycle_helpers import versioned
import pytest


def _new_template(client, headers):
    response = client.post('/api/templates', headers=headers, json={'name': 'round6 identity'})
    assert response.status_code == 200, response.text
    tid = response.json()['id']
    rows = client.get(f'/api/templates/{tid}/items', headers=headers).json()
    # A work row's id is the template task its reference documents hang on.
    return tid, [{'modules': [{'tasks': [item for section in rows['sections'] for item in section['items'] if item['kind'] == 'work']}]}]


def test_reference_delete_failure_does_not_destroy_file(client, admin_headers, monkeypatch):
    from app.routers import templates
    tid, tree = _new_template(client, admin_headers)
    task = tree[0]['modules'][0]['tasks'][0]
    base = f"/api/templates/{tid}/tasks/{task['id']}/reference-docs"
    uploaded = client.post(base, headers=admin_headers, files={'file': ('atomic.txt', b'must survive', 'text/plain')}).json()
    def fail(*args, **kwargs):
        raise RuntimeError('audit failure')
    monkeypatch.setattr(templates, 'log_change', fail)
    with pytest.raises(RuntimeError, match='audit failure'):
        client.delete(f"{base}/{uploaded['id']}", headers=admin_headers)
    downloaded = client.get(f"{base}/{uploaded['id']}/download", headers=admin_headers)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == b'must survive'


def test_template_deleted_source_cannot_silently_create_empty_copy(client, admin_headers):
    response = client.post('/api/templates', headers=admin_headers,
                           json={'name': 'Lost source', 'copy_from': 'deleted-source'})
    assert response.status_code == 404, response.text
    assert 'Lost source' not in [item['name'] for item in client.get('/api/templates', headers=admin_headers).json()]


def test_template_delete_removes_document_requirements_and_procurement_children(client, admin_headers):
    from app.db import SessionLocal
    from app.models import DocumentRequirement, TemplateProcurementItem
    tid, _ = _new_template(client, admin_headers)
    with SessionLocal() as db:
        assert db.query(DocumentRequirement).filter_by(template_id=tid).count() > 0
    assert client.delete(f'/api/templates/{tid}', headers=admin_headers).status_code == 200
    with SessionLocal() as db:
        assert db.query(DocumentRequirement).filter_by(template_id=tid).count() == 0
        assert db.query(TemplateProcurementItem).filter_by(template_id=tid).count() == 0


def _minimal_import():
    return {'type': 'agvpm-project', 'project': {'name': 'round6 import', 'start_date': '2026-01-01', 'end_date': '2026-12-31'},
            'modules': [{'name': 'module', 'phase_name': 'phase', 'tasks': [{'name': 'task', 'kind': 'other'}]}]}


@pytest.mark.parametrize('quantity', [True, 1.5])
def test_import_rejects_noninteger_vehicle_counts(client, pm_headers, quantity):
    payload = _minimal_import()
    payload['vehicles'] = [{'vehicle_type': '潜伏式', 'model_name': 'sample', 'quantity': quantity}]
    preview = client.post('/api/projects/import/preview', headers=pm_headers, json=payload)
    assert preview.json()['valid'] is False
    assert client.post('/api/projects/import/json', headers=pm_headers, json=payload).status_code == 400


def test_import_supports_existing_company_owned_preparation(client, pm_headers):
    payload = _minimal_import()
    payload['preparations'] = [{'name': '公司资源确认', 'owner_party': 'company'}]
    response = client.post('/api/projects/import/json', headers=pm_headers, json=payload)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('changes', [{'start_date': 'not-a-date'}, {'start_date': '2026-12-31', 'end_date': '2026-01-01'}])
def test_clone_rejects_invalid_period_without_creating_project(client, pm_headers, changes):
    from app.db import SessionLocal
    from app.models import Project
    original = client.post('/api/projects', headers=pm_headers, json={
        'name': 'Clone period', 'start_date': '2026-01-01', 'end_date': '2026-12-31', 'new_vehicles': False}).json()
    with SessionLocal() as db:
        count = db.query(Project).count()
    response = client.post(f"/api/projects/{original['id']}/clone", headers=pm_headers, json=changes)
    assert response.status_code in (400, 422), response.text
    with SessionLocal() as db:
        assert db.query(Project).count() == count


def test_clone_preserves_project_planning_context_but_resets_execution(client, pm_headers):
    from app.db import SessionLocal
    from app.models import Project
    original = client.post('/api/projects', headers=pm_headers, json={
        'name': 'Clone context', 'timezone': 'America/Los_Angeles', 'description': 'Scope matters',
        'start_date': '2026-01-01', 'end_date': '2026-12-31', 'need_wms': True, 'new_vehicles': False}).json()
    settings = client.put(f"/api/projects/{original['id']}/weekly-plans/settings", headers=pm_headers,
                          json=versioned(original['id'], {'rest_mode': 'two', 'skip_holidays': True}))
    assert settings.status_code == 200, settings.text
    response = client.post(f"/api/projects/{original['id']}/clone", headers=pm_headers, json={'name': 'Fresh execution'})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        copied = db.get(Project, response.json()['id'])
        assert copied.timezone == 'America/Los_Angeles'
        assert copied.description == 'Scope matters'
        assert copied.rest_mode == 'two' and copied.skip_holidays
        assert 'need_wms' in copied.prep_conditions
        assert copied.status == 'preparing'


def test_template_upload_audit_failure_removes_uncommitted_file(client, admin_headers, monkeypatch):
    from app.routers import templates
    tid, tree = _new_template(client, admin_headers)
    task = tree[0]['modules'][0]['tasks'][0]
    before = set(templates.UPLOAD_DIR.iterdir())
    def fail(*args, **kwargs): raise RuntimeError('upload audit failure')
    monkeypatch.setattr(templates, 'log_change', fail)
    with pytest.raises(RuntimeError, match='upload audit failure'):
        client.post(f"/api/templates/{tid}/tasks/{task['id']}/reference-docs", headers=admin_headers,
                    files={'file': ('uncommitted.txt', b'remove on rollback', 'text/plain')})
    assert set(templates.UPLOAD_DIR.iterdir()) == before


