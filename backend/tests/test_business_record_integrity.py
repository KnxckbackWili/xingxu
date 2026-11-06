"""Round-three regressions for portable backups and secondary business workflows."""
from tests.lifecycle_helpers import versioned
from datetime import date
from copy import deepcopy
from uuid import uuid4

from app.db import SessionLocal
from app.models import Task, Module, Phase, ArchiveChecklist


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
        db.commit()
        return ids


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
