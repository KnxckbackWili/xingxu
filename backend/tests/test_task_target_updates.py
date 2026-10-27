"""目标撤回是明确的计划修改，不能隐藏实际执行或删除既有安排。"""
from datetime import date

import pytest


def setup_task(client, headers):
    response = client.post('/api/projects', headers=headers, json={
        'name': '任务目标撤回测试', 'client': '测试客户',
        'start_date': '2026-10-05', 'end_date': '2026-10-06',
        'new_vehicles': False, 'template_id': 'default', 'module_ids': ['mod-01'],
    })
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    tree = client.get(f'/api/projects/{pid}/tree', headers=headers).json()
    response = client.post(f'/api/projects/{pid}/tasks', headers=headers, json={
        'module_id': tree[0]['modules'][0]['id'], 'name': '待核对配件',
        'quantity_type': 'manual', 'target_quantity': 2, 'unit': '台',
    })
    assert response.status_code == 200, response.text
    return pid, response.json()['id']


def read_task(client, headers, pid, tid):
    response = client.get(f'/api/projects/{pid}/tasks/{tid}/workspace', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()['task']


def add_activity(pid, tid, kind):
    from app.db import SessionLocal
    from app.models import DailyProgress, ScheduleEntry, Task, User
    with SessionLocal() as db:
        uid = db.query(User).filter_by(username='pm').one().id
        if kind in {'reported', 'corrected_to_zero', 'zero_report'}:
            amounts = {'reported': [1], 'corrected_to_zero': [1, -1], 'zero_report': [0]}[kind]
            for i, amount in enumerate(amounts):
                db.add(DailyProgress(project_id=pid, task_id=tid, user_id=uid,
                    work_date=date(2026, 10, 5), completed_quantity=amount,
                    client_uuid=f'target-activity-{i}'))
        elif kind == 'manual_complete':
            db.get(Task, tid).manually_completed = True
        else:
            db.add(ScheduleEntry(project_id=pid, task_id=tid, assignee_id=uid,
                work_date=date(2026, 10, 5), planned_quantity=2,
                is_confirmed=kind in {'issued', 'cancelled'},
                is_locked=kind in {'locked', 'cancelled'},
                status='skipped' if kind == 'cancelled' else 'done' if kind == 'done' else 'planned'))
        db.commit()


def test_omitted_target_preserves_plan_even_with_report_history(client, pm_headers):
    pid, tid = setup_task(client, pm_headers)
    add_activity(pid, tid, 'reported')
    before = read_task(client, pm_headers, pid, tid)
    response = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers,
        json={'name': '配件核对说明已修正', 'version': before['version']})
    assert response.status_code == 200, response.text
    saved = read_task(client, pm_headers, pid, tid)
    assert saved['target_quantity'] == 2
    assert saved['completed'] == 1
    assert saved['name'] == '配件核对说明已修正'


@pytest.mark.parametrize('quantity', [None, 0])
def test_explicit_empty_target_is_persisted_as_pending(client, pm_headers, quantity):
    pid, tid = setup_task(client, pm_headers)
    before = read_task(client, pm_headers, pid, tid)
    response = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers,
        json={'target_quantity': quantity, 'version': before['version']})
    assert response.status_code == 200, response.text
    assert response.json()['target_quantity'] is None
    saved = read_task(client, pm_headers, pid, tid)
    assert saved['target_quantity'] is None
    assert saved['version'] == before['version'] + 1
    tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    assert next(t for p in tree for m in p['modules'] for t in m['tasks'] if t['id'] == tid)['target_quantity'] is None


@pytest.mark.parametrize('kind, message', [
    ('reported', '报工'), ('corrected_to_zero', '报工'), ('zero_report', '报工'),
    ('manual_complete', '手动完成'), ('issued', '已下达'), ('locked', '锁定'), ('done', '已完成'),
])
@pytest.mark.parametrize('quantity', [None, 0])
def test_withdrawal_rejects_execution_history_without_partial_changes(client, pm_headers, kind, message, quantity):
    pid, tid = setup_task(client, pm_headers)
    add_activity(pid, tid, kind)
    before = read_task(client, pm_headers, pid, tid)
    response = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers,
        json={'target_quantity': quantity, 'name': '不应保存的名称', 'version': before['version']})
    assert response.status_code == 400, response.text
    assert message in response.json()['detail']
    after = read_task(client, pm_headers, pid, tid)
    assert (after['target_quantity'], after['name'], after['version'], after['completed']) == (
        before['target_quantity'], before['name'], before['version'], before['completed'])
    from app.db import SessionLocal
    from app.models import DailyProgress, ScheduleEntry
    with SessionLocal() as db:
        expected_reports = 2 if kind == 'corrected_to_zero' else 1 if kind in {'reported', 'zero_report'} else 0
        assert db.query(DailyProgress).filter_by(task_id=tid).count() == expected_reports
        assert db.query(ScheduleEntry).filter_by(task_id=tid).count() == int(kind in {'issued', 'locked', 'done'})


@pytest.mark.parametrize('kind', ['draft', 'cancelled'])
def test_withdrawal_preserves_unissued_or_cancelled_arrangements(client, pm_headers, kind):
    pid, tid = setup_task(client, pm_headers)
    add_activity(pid, tid, kind)
    response = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers, json={'target_quantity': None})
    assert response.status_code == 200, response.text
    assert read_task(client, pm_headers, pid, tid)['target_quantity'] is None
    from app.db import SessionLocal
    from app.models import ScheduleEntry
    with SessionLocal() as db:
        entry = db.query(ScheduleEntry).filter_by(task_id=tid).one()
        assert entry.planned_quantity == 2
        assert entry.status == ('skipped' if kind == 'cancelled' else 'planned')
        assert entry.is_confirmed == (kind == 'cancelled')
        assert entry.is_locked == (kind == 'cancelled')


def test_positive_target_still_rejects_below_actual_and_allows_increase(client, pm_headers):
    pid, tid = setup_task(client, pm_headers)
    add_activity(pid, tid, 'reported')
    path = f'/api/projects/{pid}/tasks/{tid}'
    assert client.put(path, headers=pm_headers, json={'target_quantity': 0.5}).status_code == 400
    assert read_task(client, pm_headers, pid, tid)['target_quantity'] == 2
    assert client.put(path, headers=pm_headers, json={'target_quantity': 3}).status_code == 200
    assert read_task(client, pm_headers, pid, tid)['target_quantity'] == 3


def test_stale_version_cannot_clear_target(client, pm_headers):
    pid, tid = setup_task(client, pm_headers)
    before = read_task(client, pm_headers, pid, tid)
    response = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers,
        json={'target_quantity': None, 'version': before['version'] + 1})
    assert response.status_code == 409
    after = read_task(client, pm_headers, pid, tid)
    assert after['target_quantity'] == 2
    assert after['version'] == before['version']


def test_already_pending_manual_completion_can_keep_target_while_editing_metadata(client, pm_headers):
    pid, tid = setup_task(client, pm_headers)
    from app.db import SessionLocal
    from app.models import Task
    with SessionLocal() as db:
        task = db.get(Task, tid)
        task.target_quantity = None
        task.manually_completed = True
        db.commit()
    response = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers,
        json={'target_quantity': None, 'name': '补充已完成任务说明'})
    assert response.status_code == 200, response.text
    after = read_task(client, pm_headers, pid, tid)
    assert after['target_quantity'] is None
    assert after['manually_completed']
    assert after['name'] == '补充已完成任务说明'


@pytest.mark.parametrize('missing_quantity', [None, 0])
def test_mixed_draft_confirmation_is_atomic_until_positive_target_is_restored(client, pm_headers, missing_quantity):
    pid, tid = setup_task(client, pm_headers)
    from app.db import SessionLocal
    from app.models import ChangeLog, Notification, Project, ScheduleEntry, Task, User
    with SessionLocal() as db:
        task = db.get(Task, tid)
        task.target_quantity = missing_quantity
        user = db.query(User).filter_by(username='worker1').one()
        project = db.get(Project, pid)
        project.status = 'planning'
        project.members = [user.id]
        project.schedule_version = 4
        valid = Task(project_id=pid, module_id=task.module_id, name='已有目标的正常任务', target_quantity=3)
        legacy = Task(project_id=pid, module_id=task.module_id, name='旧已下达无目标任务', target_quantity=None)
        cancelled = Task(project_id=pid, module_id=task.module_id, name='已取消无目标任务', target_quantity=None)
        db.add_all([valid, legacy, cancelled]); db.flush()
        ids = ['pending-empty', 'pending-valid', 'issued-legacy', 'cancelled-empty']
        db.add_all([
            ScheduleEntry(id=ids[0], project_id=pid, task_id=tid, assignee_id=user.id,
                work_date=date(2026, 10, 5), planned_quantity=2, is_confirmed=False, version=3),
            ScheduleEntry(id=ids[1], project_id=pid, task_id=valid.id, assignee_id=user.id,
                work_date=date(2026, 10, 5), planned_quantity=3, is_confirmed=False, version=7),
            ScheduleEntry(id=ids[2], project_id=pid, task_id=legacy.id, assignee_id=user.id,
                work_date=date(2026, 10, 5), planned_quantity=1, is_confirmed=True, version=6),
            ScheduleEntry(id=ids[3], project_id=pid, task_id=cancelled.id, assignee_id=user.id,
                work_date=date(2026, 10, 5), planned_quantity=1, status='skipped', is_confirmed=False, version=5),
        ])
        db.commit()

    def snapshot():
        with SessionLocal() as db:
            project = db.get(Project, pid)
            return {
                'entries': [(e.id, e.is_confirmed, e.version, e.status, e.planned_quantity)
                    for e in db.query(ScheduleEntry).filter_by(project_id=pid).order_by(ScheduleEntry.id)],
                'project': (project.status, project.schedule_version, project.version),
                'logs': db.query(ChangeLog).filter_by(project_id=pid).count(),
                'notifications': db.query(Notification).filter_by(project_id=pid).count(),
            }

    before = snapshot()
    path = f'/api/projects/{pid}/schedule/confirm'
    response = client.post(path, headers=pm_headers)
    assert response.status_code == 400, response.text
    assert '待核对配件' in response.json()['detail']
    assert '目标数量' in response.json()['detail']
    assert snapshot() == before

    assert client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers,
        json={'target_quantity': 2}).status_code == 200
    response = client.post(path, headers=pm_headers)
    assert response.status_code == 200, response.text
    assert response.json()['schedule_version'] == 5
    after = snapshot()
    entries = {e[0]: e for e in after['entries']}
    assert entries['pending-empty'][1:3] == (True, 4)
    assert entries['pending-valid'][1:3] == (True, 8)
    assert entries['issued-legacy'][1:3] == (True, 6)
    assert entries['cancelled-empty'][1:4] == (False, 5, 'skipped')
    assert len(entries) == 4
    assert after['project'][0] == 'ready'


def active_assignment_context(client, headers, missing_quantity, *, issued=False, skipped=False):
    pid, tid = setup_task(client, headers)
    from app.db import SessionLocal
    from app.models import Project, ScheduleEntry, Task, User
    with SessionLocal() as db:
        project = db.get(Project, pid)
        project.status = 'preparing'
        worker = db.query(User).filter_by(username='worker1').one()
        project.members = [worker.id]
        db.get(Task, tid).target_quantity = missing_quantity
        entry = ScheduleEntry(project_id=pid, task_id=tid, assignee_id=worker.id,
            work_date=date(2026, 10, 5), planned_quantity=1, version=3,
            is_confirmed=issued, is_locked=issued,
            status='skipped' if skipped else 'planned', notes='原安排备注')
        db.add(entry); db.commit()
        return pid, tid, worker.id, entry.id


def assignment_snapshot(pid):
    from app.db import SessionLocal
    from app.models import ChangeLog, Notification, Project, ScheduleEntry, Task
    with SessionLocal() as db:
        project = db.get(Project, pid)
        return {
            'entries': [(e.id, e.work_date, e.assignee_id, e.planned_quantity, e.status,
                e.is_confirmed, e.is_locked, e.version, e.notes)
                for e in db.query(ScheduleEntry).filter_by(project_id=pid).order_by(ScheduleEntry.id)],
            'tasks': db.query(Task).filter_by(project_id=pid).count(),
            'project': (project.status, project.schedule_version, project.version),
            'logs': db.query(ChangeLog).filter_by(project_id=pid).count(),
            'notifications': db.query(Notification).filter_by(project_id=pid).count(),
        }


@pytest.mark.parametrize('quantity', [None, 0])
def test_manual_existing_work_rejects_empty_target_atomically_then_accepts_corrected_plan(client, pm_headers, quantity):
    pid, tid, uid, _ = active_assignment_context(client, pm_headers, quantity)
    body = {'task_id': tid, 'assignee_id': uid, 'work_date': '2026-10-06',
        'planned_quantity': 1, 'notes': '新增已有工作安排'}
    before = assignment_snapshot(pid)
    response = client.post(f'/api/projects/{pid}/schedule/manual', headers=pm_headers, json=body)
    assert response.status_code == 400, response.text
    assert '待核对配件' in response.json()['detail']
    assert '目标数量' in response.json()['detail']
    assert assignment_snapshot(pid) == before
    assert client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers,
        json={'target_quantity': 2}).status_code == 200
    response = client.post(f'/api/projects/{pid}/schedule/manual', headers=pm_headers, json=body)
    assert response.status_code == 200, response.text
    after = assignment_snapshot(pid)
    assert len(after['entries']) == len(before['entries']) + 1
    entry = next(e for e in after['entries'] if e[1] == date(2026, 10, 6))
    assert entry[3:7] == (1, 'planned', True, True)


@pytest.mark.parametrize('quantity', [None, 0])
@pytest.mark.parametrize('action', ['issue_draft', 'change_date', 'unassign', 'change_quantity', 'mark_done', 'reactivate_cancelled'])
def test_empty_target_cannot_be_issued_or_change_active_execution(client, pm_headers, quantity, action):
    pid, _, _, eid = active_assignment_context(client, pm_headers, quantity,
        issued=action != 'issue_draft', skipped=action == 'reactivate_cancelled')
    changes = {
        'issue_draft': {'is_confirmed': True, 'is_locked': True},
        'change_date': {'work_date': '2026-10-06'},
        'unassign': {'assignee_id': None},
        'change_quantity': {'planned_quantity': 2},
        'mark_done': {'status': 'done'},
        'reactivate_cancelled': {'status': 'planned', 'is_confirmed': True},
    }[action]
    before = assignment_snapshot(pid)
    response = client.put(f'/api/schedule/{eid}', headers=pm_headers,
        json={**changes, 'notes': '失败时不能保存此备注', 'version': 3})
    assert response.status_code == 400, response.text
    assert '目标数量' in response.json()['detail']
    assert assignment_snapshot(pid) == before


@pytest.mark.parametrize('quantity', [None, 0])
def test_legacy_issued_work_allows_notes_with_unchanged_execution_fields(client, pm_headers, quantity):
    pid, _, uid, eid = active_assignment_context(client, pm_headers, quantity, issued=True)
    before = assignment_snapshot(pid)['entries'][0]
    response = client.put(f'/api/schedule/{eid}', headers=pm_headers, json={
        'work_date': '2026-10-05', 'assignee_id': uid, 'planned_quantity': 1,
        'is_confirmed': True, 'is_locked': True, 'notes': '仅补充历史说明', 'version': 3,
    })
    assert response.status_code == 200, response.text
    after = assignment_snapshot(pid)['entries'][0]
    assert after[:7] == before[:7]
    assert after[7:] == (4, '仅补充历史说明')


def test_legacy_empty_target_allows_explicit_cancellation_and_unissued_draft_edits(client, pm_headers):
    pid, _, _, eid = active_assignment_context(client, pm_headers, None, issued=True)
    assert client.put(f'/api/schedule/{eid}', headers=pm_headers,
        json={'status': 'skipped', 'version': 3}).status_code == 200
    cancelled = assignment_snapshot(pid)['entries'][0]
    assert cancelled[4:8] == ('skipped', True, True, 4)
    pid, _, _, eid = active_assignment_context(client, pm_headers, None)
    assert client.put(f'/api/schedule/{eid}', headers=pm_headers, json={
        'planned_quantity': 2, 'work_date': '2026-10-06', 'notes': '保留未下达草稿', 'version': 3,
    }).status_code == 200
    draft = assignment_snapshot(pid)['entries'][0]
    assert draft[3:8] == (2, 'planned', False, False, 4)


def test_new_temporary_work_keeps_automatic_target_one(client, pm_headers):
    pid, _, uid, _ = active_assignment_context(client, pm_headers, None)
    response = client.post(f'/api/projects/{pid}/schedule/manual', headers=pm_headers, json={
        'assignee_id': uid, 'work_date': '2026-10-06', 'title': '临时排查连接', 'estimated_hours': 2,
    })
    assert response.status_code == 200, response.text
    task = read_task(client, pm_headers, pid, response.json()['task_id'])
    assert task['target_quantity'] == 1
    assert task['quantity_type'] == 'fixed'


@pytest.mark.parametrize('kind', ['issued', 'locked'])
def test_legacy_null_schedule_status_still_protects_target_withdrawal(client, pm_headers, kind):
    pid, tid = setup_task(client, pm_headers)
    add_activity(pid, tid, kind)
    from sqlalchemy import update
    from app.db import SessionLocal
    from app.models import ScheduleEntry
    with SessionLocal() as db:
        db.execute(update(ScheduleEntry).where(ScheduleEntry.task_id == tid).values(status=None))
        db.commit()
    response = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers, json={'target_quantity': None})
    assert response.status_code == 400, response.text
    assert read_task(client, pm_headers, pid, tid)['target_quantity'] == 2
