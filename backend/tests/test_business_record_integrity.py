"""Round-three regressions for portable backups and secondary business workflows."""
from tests.lifecycle_helpers import versioned
from datetime import date
from copy import deepcopy
from uuid import uuid4

from app.db import SessionLocal
from app.models import Task, Module, Phase, DailyProgress, ScheduleEntry, ArchiveChecklist


def make_project(client, headers, name='记录完整性'):
    r = client.post('/api/projects', headers=headers, json={
        'name': name, 'start_date': '2026-09-01', 'end_date': '2026-10-31', 'new_vehicles': False})
    assert r.status_code == 200, r.text
    return r.json()['id']


def add_same_name_tasks(project_id, user_id):
    with SessionLocal() as db:
        phase = Phase(project_id=project_id, name='调试')
        db.add(phase); db.flush()
        ids = []
        for index in range(2):
            module = Module(project_id=project_id, phase_id=phase.id, name=f'模块{index}')
            db.add(module); db.flush()
            task = Task(project_id=project_id, module_id=module.id, name='检查', quantity_type='manual', target_quantity=10)
            db.add(task); db.flush()
            ids.append(task.id)
            db.add(DailyProgress(project_id=project_id, task_id=task.id, user_id=user_id,
                work_date=date(2026, 9, 30), completed_quantity=index + 1, client_uuid=str(uuid4())))
            db.add(ScheduleEntry(project_id=project_id, task_id=task.id, work_date=date(2026, 9, 30), planned_quantity=index + 3))
        db.commit()
        return ids


def test_same_named_tasks_backup_roundtrip(client, admin_headers):
    pid = make_project(client, admin_headers)
    uid = client.get('/api/auth/me', headers=admin_headers).json()['id']
    ids = add_same_name_tasks(pid, uid)
    snapshot = client.get(f'/api/projects/{pid}/export/json', headers=admin_headers).json()
    assert {t['source_id'] for m in snapshot['modules'] for t in m['tasks']} == set(ids)
    assert {r['task_source_id'] for r in snapshot['progress']} == set(ids)
    result = client.post('/api/projects/import/json', headers=admin_headers, json=snapshot)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        new_pid = result.json()['id']
        # A new-project import keeps each same-named work definition distinct; retired
        # daily facts are not replayed into the new project (full restore keeps them).
        imported = db.query(Task).filter_by(project_id=new_pid, name='检查').all()
        assert sorted(task.group_label for task in imported) == ['模块0', '模块1']
        assert not {task.id for task in imported} & set(ids)
        assert not db.query(DailyProgress).filter(DailyProgress.task_id.in_([t.id for t in imported])).count()
    # Legacy ambiguous snapshots fail explicitly rather than misassigning history.
    legacy = deepcopy(snapshot)
    for module in legacy['modules']:
        for task in module['tasks']:
            task.pop('source_id')
    for key in ('schedule', 'progress'):
        for record in legacy[key]:
            record.pop('task_source_id')
    rejected = client.post('/api/projects/import/json', headers=admin_headers, json=legacy)
    assert rejected.status_code == 400
    assert 'source_id' in rejected.json()['detail']
    # Stable task IDs must be supplied when references would otherwise be ambiguous.
    missing_ref = deepcopy(snapshot)
    missing_ref['progress'][0].pop('task_source_id')
    rejected = client.post('/api/projects/import/json', headers=admin_headers, json=missing_ref)
    assert rejected.status_code == 400
    assert '有重名' in rejected.json()['detail']
    bad_ref = deepcopy(snapshot)
    bad_ref['progress'][0]['task_source_id'] = 'missing'
    assert client.post('/api/projects/import/json', headers=admin_headers, json=bad_ref).status_code == 400
    bad_ref['progress'][0]['task_source_id'] = None
    assert client.post('/api/projects/import/json', headers=admin_headers, json=bad_ref).status_code == 400
    duplicate_id = deepcopy(snapshot)
    duplicate_id['modules'][1]['tasks'][0]['source_id'] = duplicate_id['modules'][0]['tasks'][0]['source_id']
    assert client.post('/api/projects/import/json', headers=admin_headers, json=duplicate_id).status_code == 400


def test_clone_resets_document_history_and_work_records_without_changing_source(client, admin_headers):
    from tests.document_helpers import documents, upload_documents
    pid = make_project(client, admin_headers)
    uid = client.get('/api/auth/me', headers=admin_headers).json()['id']
    add_same_name_tasks(pid, uid)
    source = documents(client, admin_headers, pid)['documents'][0]
    original = upload_documents(client, admin_headers, pid, [source['id']])['documents'][0]
    result = client.post(f'/api/projects/{pid}/clone', headers=admin_headers,
        json={'name': '新一期', 'start_date': '2026-11-01', 'end_date': '2026-12-01'})
    assert result.status_code == 200, result.text
    target = documents(client, admin_headers, result.json()['id'])
    assert all(row['status'] == 'pending' and not row['versions'] for row in target['documents'])
    assert all(row['id'] != original['id'] for row in target['documents'])
    kept = next(row for row in documents(client, admin_headers, pid)['documents'] if row['id'] == original['id'])
    assert kept['status'] == 'submitted' and kept['versions'] == original['versions']
    with SessionLocal() as db:
        assert db.query(DailyProgress).filter_by(project_id=result.json()['id']).count() == 0


def test_document_withdrawal_keeps_immutable_file_history(client, admin_headers):
    from tests.document_helpers import documents, upload_documents
    pid = make_project(client, admin_headers)
    row = documents(client, admin_headers, pid)['documents'][0]
    submitted = upload_documents(client, admin_headers, pid, [row['id']])['documents'][0]
    path = f'/api/projects/{pid}/documents/{row["id"]}'
    assert client.put(path, headers=admin_headers, json={'status': 'pending', 'version': submitted['version']}).status_code == 422
    result = client.put(path, headers=admin_headers, json={'status': 'pending', 'reason': '需要补充客户签字', 'version': submitted['version']})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'pending' and result.json()['versions'] == submitted['versions']
    aid = submitted['versions'][0]['attachment_id']
    assert client.delete('/api/files/' + aid, headers=admin_headers).status_code == 400


def test_closing_one_vehicle_issue_retains_other_fault(client, admin_headers):
    pid = make_project(client, admin_headers)
    uid = client.post(f'/api/projects/{pid}/vehicle-units', headers=admin_headers, json={'asset_code': 'AGV-001'}).json()['id']
    base = f'/api/projects/{pid}/vehicle-units/{uid}'
    events = []
    for title in ('传感器问题', '制动停机'):
        response = client.post(base + '/events', headers=admin_headers, json={
            'event_type': 'fault', 'event_date': '2026-09-30', 'title': title, 'status_after': 'stopped'})
        assert response.status_code == 200, response.text
        events.append(response.json()['id'])
    response = client.put(base + '/events/' + events[0], headers=admin_headers, json={'is_closed': True, 'status_after': 'normal'})
    assert response.status_code == 200, response.text
    detail = client.get(base, headers=admin_headers).json()
    assert detail['current_status'] == 'stopped' and detail['open_issue_count'] == 1
    client.put(base, headers=admin_headers, json={'current_status': 'normal'})
    assert client.get(base, headers=admin_headers).json()['current_status'] == 'stopped'
    # A new already-resolved note likewise must not clear the pending stop.
    client.post(base + '/events', headers=admin_headers, json={
        'event_type': 'inspection', 'event_date': '2026-09-30', 'title': '另一项检查完成', 'is_closed': True, 'status_after': 'normal'})
    assert client.get(base, headers=admin_headers).json()['current_status'] == 'stopped'
    client.put(base + '/events/' + events[1], headers=admin_headers, json={'is_closed': True, 'status_after': 'normal'})
    detail = client.get(base, headers=admin_headers).json()
    assert detail['current_status'] == 'normal' and detail['open_issue_count'] == 0


def test_replenishment_restores_consumed_inventory_only(client, admin_headers):
    pid = make_project(client, admin_headers)
    base = f'/api/projects/{pid}/inventory'
    item = client.post(base, headers=admin_headers, json={'name': '扎带', 'quantity': 2}).json()['id']
    url = base + '/' + item + '/movements'
    depleted = client.post(url, headers=admin_headers, json={'movement_type': 'consume', 'quantity': 2})
    assert depleted.json()['item']['status'] == 'consumed'
    # A zero-quantity receipt must not imply that stock is available again.
    zero = client.post(url, headers=admin_headers, json={'movement_type': 'receive', 'quantity': 0})
    assert zero.json()['item']['status'] == 'consumed'
    received = client.post(url, headers=admin_headers, json={'movement_type': 'receive', 'quantity': 3})
    assert received.json()['item']['quantity'] == 3
    assert received.json()['item']['status'] == 'on_site'
    for status in ('damaged', 'lost', 'scrapped', 'in_use'):
        other = client.post(base, headers=admin_headers, json={'name': status, 'quantity': 0, 'status': status}).json()['id']
        response = client.post(base + '/' + other + '/movements', headers=admin_headers,
            json={'movement_type': 'return_site', 'quantity': 1})
        assert response.json()['item']['status'] == status


def test_partial_handover_plan_preserves_hidden_fields_and_explicit_clear(client, admin_headers):
    pid = make_project(client, admin_headers)
    url = f'/api/projects/{pid}'
    original = {'mode': 'collective', 'meeting_point': '东门',
                'transport': '大巴', 'notes': '原备注'}
    assert client.put(url, headers=admin_headers, json=versioned(pid, {'entry_plan': original})).status_code == 200
    assert client.put(url, headers=admin_headers, json=versioned(pid, {'entry_plan': {'notes': '新备注'}})).status_code == 200
    updated = client.get(url, headers=admin_headers).json()['entry_plan']
    assert updated == {**original, 'notes': '新备注'}
    assert client.put(url, headers=admin_headers, json=versioned(pid, {'entry_plan': {'meeting_point': ''}})).status_code == 200
    updated = client.get(url, headers=admin_headers).json()['entry_plan']
    assert updated['meeting_point'] == ''
    assert updated['transport'] == '大巴'
    assert client.put(url, headers=admin_headers, json=versioned(pid, {'entry_plan': None})).status_code == 200
    assert client.get(url, headers=admin_headers).json()['entry_plan'] == {}
