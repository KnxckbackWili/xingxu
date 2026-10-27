"""Regression coverage for execution authorization and quality follow-up."""
from datetime import date
import pytest


def _execution(client, *, manager='user-pm-001', status='executing'):
    from app.db import SessionLocal
    from app.models import Project, ProjectMember, Phase, Module, Task, CheckItem
    with SessionLocal() as db:
        p = Project(name='执行回归', manager=manager, members=['user-worker-001'],
                    status=status, start_date=date.today(), end_date=date.today())
        db.add(p); db.flush()
        db.add_all([ProjectMember(project_id=p.id, user_id=manager, role='manager'),
                    ProjectMember(project_id=p.id, user_id='user-worker-001')])
        phase = Phase(project_id=p.id, name='现场实施'); db.add(phase); db.flush()
        mod = Module(project_id=p.id, phase_id=phase.id, name='实施'); db.add(mod); db.flush()
        task = Task(project_id=p.id, module_id=mod.id, name='调试', quantity_type='fixed', target_quantity=10)
        db.add(task); db.flush()
        ci = CheckItem(project_id=p.id, task_id=task.id, name='普通检查')
        db.add(ci); db.commit()
        return p.id, task.id, ci.id


@pytest.mark.parametrize('operation', ['report', 'complete', 'reopen'])
def test_unrelated_pm_cannot_mutate_execution(client, pm_headers, operation):
    pid, tid, _ = _execution(client, manager='user-admin-001')
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).status_code == 404
    if operation == 'report':
        url, body = '/api/worker/reports', dict(task_id=tid, work_date=date.today().isoformat(), completed_quantity=1, client_uuid='scope-report-01')
    else:
        url, body = f'/api/worker/tasks/{tid}/{operation}', {}
    response = client.post(url, headers=pm_headers, json=body)
    assert response.status_code == 404, response.text


def test_worker_can_mark_non_safety_check_not_applicable(client, worker_headers):
    pid, _, cid = _execution(client)
    response = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=worker_headers,
                          json={'is_applicable': False, 'not_applicable_reason': '现场无此配置'})
    assert response.status_code == 200, response.text
    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        ci = db.get(CheckItem, cid)
        assert ci.is_applicable is False and ci.not_applicable_set_by == 'user-worker-001'


def test_archived_check_cannot_be_changed(client, worker_headers):
    pid, _, cid = _execution(client, status='archived')
    response = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=worker_headers, json={'failed': True, 'failed_reason': '归档后修改'})
    assert response.status_code == 400, response.text


def test_worker_na_requires_reason_and_rejects_safety_check(client, worker_headers):
    pid, _, cid = _execution(client)
    url = f'/api/projects/{pid}/check-items/{cid}'
    assert client.put(url, headers=worker_headers, json={'is_applicable': False}).status_code == 400
    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        db.get(CheckItem, cid).is_safety_critical = True; db.commit()
    assert client.put(url, headers=worker_headers, json={'is_applicable': False, 'not_applicable_reason': '不可跳过'}).status_code == 400


def test_distinct_offline_reports_preserve_both_quantities(client, worker_headers):
    pid, tid, _ = _execution(client)
    ops = [dict(type='report', client_uuid=f'offline-add-{n}', payload={
        'task_id': tid, 'work_date': date.today().isoformat(),
        'completed_quantity': n, 'client_uuid': f'offline-add-{n}'}) for n in (1, 2)]
    response = client.post('/api/worker/sync', headers=worker_headers, json={'ops': ops})
    assert response.status_code == 200 and len(response.json()['accepted']) == 2, response.text
    from app.db import SessionLocal
    from app.services.progress import task_completed
    with SessionLocal() as db:
        assert task_completed(db, tid) == 3
    # Replaying the same batch must not add either quantity again.
    assert client.post('/api/worker/sync', headers=worker_headers, json={'ops': ops}).status_code == 200
    with SessionLocal() as db:
        assert task_completed(db, tid) == 3




@pytest.mark.parametrize('role,confirmed,status,expected', [
    ('worker', True, 'skipped', 400), ('pm', True, 'skipped', 400),
    ('worker', False, 'planned', 400), ('pm', False, 'planned', 200),
    ('worker', True, 'planned', 200),
])
def test_report_respects_schedule_release_and_cancellation(client, worker_headers, pm_headers, role, confirmed, status, expected):
    pid, tid, _ = _execution(client)
    from app.db import SessionLocal
    from app.models import ScheduleEntry
    from app.time_utils import project_today
    with SessionLocal() as db:
        entry = ScheduleEntry(project_id=pid, task_id=tid, work_date=project_today('Asia/Shanghai'),
                              assignee_id='user-worker-001', planned_quantity=10,
                              is_confirmed=confirmed, status=status)
        db.add(entry); db.commit(); eid = entry.id
    headers = worker_headers if role == 'worker' else pm_headers
    response = client.post('/api/worker/reports', headers=headers, json={
        'task_id': tid, 'schedule_entry_id': eid, 'work_date': project_today('Asia/Shanghai').isoformat(),
        'completed_quantity': 1, 'client_uuid': 'schedule-gate-01'})
    assert response.status_code == expected, response.text
    today = client.get('/api/worker/today', headers=worker_headers).json()['items']
    if status == 'skipped' or not confirmed:
        assert not any(item['entry_id'] == eid for item in today)
    else:
        assert any(item['entry_id'] == eid for item in today)


def test_cancelled_entry_still_acknowledges_already_saved_retry(client, worker_headers):
    pid, tid, _ = _execution(client)
    from app.db import SessionLocal
    from app.models import ScheduleEntry
    with SessionLocal() as db:
        entry = ScheduleEntry(project_id=pid, task_id=tid, work_date=date.today(), planned_quantity=10, is_confirmed=True)
        db.add(entry); db.commit(); eid = entry.id
    body = {'task_id': tid, 'schedule_entry_id': eid, 'work_date': date.today().isoformat(),
            'completed_quantity': 1, 'client_uuid': 'cancel-retry-01'}
    assert client.post('/api/worker/reports', headers=worker_headers, json=body).json()['accepted'] is True
    with SessionLocal() as db:
        db.get(ScheduleEntry, eid).status = 'skipped'; db.commit()
    response = client.post('/api/worker/reports', headers=worker_headers, json=body)
    assert response.status_code == 200 and response.json()['accepted'] is False
