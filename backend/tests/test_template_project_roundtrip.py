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
            'modules': [{'name': 'module', 'phase_name': 'phase', 'tasks': [{'name': 'task', 'quantity_type': 'fixed', 'target_quantity': 1}]}]}


@pytest.mark.parametrize('field,value', [('target_quantity', 'nan'), ('target_quantity', 'inf'), ('standard_hours', 'NaN')])
def test_import_rejects_nonfinite_task_values(client, pm_headers, field, value):
    from app.db import SessionLocal
    from app.models import Project
    payload = _minimal_import()
    payload['modules'][0]['tasks'][0][field] = value
    preview = client.post('/api/projects/import/preview', headers=pm_headers, json=payload)
    assert preview.status_code == 200
    assert preview.json()['valid'] is False, preview.text
    imported = client.post('/api/projects/import/json', headers=pm_headers, json=payload)
    assert imported.status_code == 400
    with SessionLocal() as db:
        assert db.query(Project).filter_by(name='round6 import').count() == 0


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


def test_import_keeps_legacy_approval_as_readonly_source_without_submitted_evidence(client, pm_headers):
    from tests.document_helpers import documents
    from app.db import SessionLocal
    from app.models import Task
    payload = _minimal_import()
    original = {'name': 'Signed evidence', 'required': True, 'doc_type': 'PDF', 'note': 'Customer signed',
        'attachment_id': 'foreign-file', 'status': 'accepted', 'done': True,
        'submitted_by': 'source-user', 'reviewed_by': 'source-reviewer', 'reviewed_at': '2026-01-01'}
    payload['modules'][0]['tasks'][0]['deliverables'] = [original]
    preview = client.post('/api/projects/import/preview', headers=pm_headers, json=payload).json()
    assert preview['valid'] and preview['warnings']
    assert preview['summary']['legacy_document_requirements'] == 1
    response = client.post('/api/projects/import/json', headers=pm_headers, json=payload)
    assert response.status_code == 200 and response.json()['warnings'], response.text
    state = documents(client, pm_headers, response.json()['id'])
    definition = next(row for row in state['definitions'] if row['name'] == original['name'])
    assert definition['stage_key'] == 'legacy' and definition['source_metadata']['original']['original'] == original
    assert all(row['status'] == 'pending' and not row['versions'] for row in state['documents'])
    with SessionLocal() as db:
        assert not db.query(Task).filter_by(project_id=response.json()['id']).one().deliverables


@pytest.mark.parametrize('dependencies', [['missing'], ['self']])
def test_import_rejects_unresolved_or_cyclic_dependency_before_write(client, pm_headers, dependencies):
    payload = _minimal_import()
    payload['modules'][0]['tasks'][0].update(source_id='self', depends_on=dependencies)
    preview = client.post('/api/projects/import/preview', headers=pm_headers, json=payload)
    assert preview.status_code == 200 and preview.json()['valid'] is False
    assert client.post('/api/projects/import/json', headers=pm_headers, json=payload).status_code == 400


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


def test_legacy_string_requirement_roundtrip_stays_unclassified_source(client, pm_headers):
    from tests.document_helpers import documents
    payload = _minimal_import()
    payload['modules'][0]['tasks'][0]['deliverables'] = ['验收报告']
    assert client.post('/api/projects/import/preview', headers=pm_headers, json=payload).json()['valid']
    created = client.post('/api/projects/import/json', headers=pm_headers, json=payload)
    assert created.status_code == 200, created.text
    state = documents(client, pm_headers, created.json()['id'])
    source = next(row for row in state['definitions'] if row['name'] == '验收报告')
    assert source['stage_key'] == 'legacy'
    assert source['source_metadata']['original']['original'] == '验收报告'
    snapshot = client.get(f'/api/projects/{created.json()["id"]}/export/json', headers=pm_headers).json()
    imported = client.post('/api/projects/import/json', headers=pm_headers, json=snapshot)
    assert imported.status_code == 200, imported.text
    target = documents(client, pm_headers, imported.json()['id'])
    kept = next(row for row in target['definitions'] if row['name'] == '验收报告')
    assert kept['stage_key'] == 'legacy' and '验收报告' in str(kept['source_metadata'])
    assert all(row['status'] == 'pending' and not row['versions'] for row in target['documents'])
