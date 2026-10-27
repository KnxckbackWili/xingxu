"""Selecting execution work is the single input for its preparation checklist."""
from app.db import SessionLocal
from app.models import Module, Task, Project


def create(client, headers, **scope):
    result = client.post('/api/projects', headers=headers, json={
        'name': '范围与准备联动', 'start_date': '2026-09-16', 'end_date': '2026-12-31',
        'new_vehicles': False, **scope})
    assert result.status_code == 200, result.text
    return result.json()['id']


def names(client, headers, pid):
    state = client.get(f'/api/projects/{pid}/documents', headers=headers).json()
    return {item['name'] for item in state['definitions'] if item['stage_key'] != 'legacy'}


def test_charging_scope_keeps_business_association_without_automatic_procurement(client, pm_headers):
    pid = create(client, pm_headers, module_ids=['mod-15'])
    assert client.get(f'/api/projects/{pid}/procurements', headers=pm_headers).json()['items'] == []
    with SessionLocal() as db:
        assert 'need_charging' in db.get(Project, pid).prep_conditions
    state = client.get(f'/api/projects/{pid}/documents', headers=pm_headers).json()
    assert len([row for row in state['definitions'] if row['stage_key'] != 'legacy']) == 53
    assert not any(row['stage_key'] == 'legacy' for row in state['documents'])


def test_deselected_or_all_excluded_work_does_not_bring_preparations(client, pm_headers):
    with SessionLocal() as db:
        excluded = [t.id for t in db.query(Task).filter_by(module_id='mod-15').all()]
    for modules, exclusions in (([], []), (['mod-15'], excluded)):
        pid = create(client, pm_headers, module_ids=modules, exclude_task_ids=exclusions)
        assert '充电设备交付' not in names(client, pm_headers, pid)
        assert '客户系统接口文档（WMS/MES）' not in names(client, pm_headers, pid)


def test_wms_is_real_optional_work_and_copy_and_rename_keep_links(client, admin_headers, pm_headers):
    copied = client.post('/api/templates', headers=admin_headers, json={'name': '客户定制方案', 'copy_from': 'default'})
    assert copied.status_code == 200, copied.text
    tid = copied.json()['id']
    tree = client.get(f'/api/templates/{tid}/tree', headers=pm_headers).json()
    module = next(m for phase in tree for m in phase['modules'] if m['name'] == 'WMS/MES 对接')
    assert module['preparation_conditions'] == ['need_wms']
    assert not module['is_selected'] and len(module['tasks']) == 3
    module['name'] = '客户订单集成'
    response = client.put(f'/api/templates/{tid}/tree', headers=admin_headers, json={'phases': tree})
    assert response.status_code == 200, response.text
    pid = create(client, pm_headers, template_id=tid, module_ids=[module['id']])
    with SessionLocal() as db:
        assert 'need_wms' in db.get(Project, pid).prep_conditions
    assert client.get(f'/api/projects/{pid}/procurements', headers=pm_headers).json()['items'] == []
    project_tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    assert len(project_tree[0]['modules'][0]['tasks']) == 3


def test_later_added_work_preserves_project_document_identity_and_evidence(client, pm_headers):
    from tests.document_helpers import documents, upload_documents
    pid = create(client, pm_headers, module_ids=['mod-03'])
    before = documents(client, pm_headers, pid)
    row = before['documents'][0]
    submitted = upload_documents(client, pm_headers, pid, [row['id']])['documents'][0]
    path = f'/api/projects/{pid}/tasks/generate'
    for _ in range(2):
        assert client.post(path, headers=pm_headers, json={'module_ids': ['mod-15']}).status_code == 200
    after = documents(client, pm_headers, pid)
    assert {row['id'] for row in after['definitions']} == {row['id'] for row in before['definitions']}
    kept = next(item for item in after['documents'] if item['id'] == row['id'])
    assert kept['status'] == 'submitted' and kept['versions'] == submitted['versions']
    assert client.get(f'/api/projects/{pid}/procurements', headers=pm_headers).json()['items'] == []


def test_upgrade_is_idempotent_and_never_changes_existing_projects(client, pm_headers):
    from app.seed.scope_preparations import migrate_scope_preparations
    pid = create(client, pm_headers, module_ids=['mod-03'])
    before = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    with SessionLocal() as db:
        count = db.query(Module).count()
        migrate_scope_preparations(db)
        migrate_scope_preparations(db)
        db.commit()
        assert db.query(Module).count() == count
    assert client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json() == before
