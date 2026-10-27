"""问题归属、闭环权限、导入原子性与去重。"""

from datetime import timedelta
import pytest
from sqlalchemy.exc import IntegrityError
from app.time_utils import utcnow

def _project(client, pm_headers, name='功能边界项目'):
    r = client.post('/api/projects', headers=pm_headers, json={'name': name, 'start_date': '2026-08-10', 'status': 'preparing', 'new_vehicles': False, 'end_date': '2026-09-30'})
    assert r.status_code == 200, r.json()
    return r.json()['id']

def test_create_issue_bad_assignee_returns_400(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '坏处理人', 'assignee_id': 'no-such-user'})
    assert r.status_code == 400
    assert '处理人' in r.json()['detail']

def _add_worker(client, pm_headers, worker_headers, pid):
    wid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    r = client.get(f'/api/projects/{pid}', headers=pm_headers)
    members = list(r.json()['members'])
    if wid not in members:
        members.append(wid)
    r = client.put(f'/api/projects/{pid}', headers=pm_headers, json={'members': members})
    assert r.status_code == 200, r.json()
    return wid

def test_assigned_worker_can_process_own_issue(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    wid = _add_worker(client, pm_headers, worker_headers, pid)
    r = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '现场设备故障', 'severity': 'high', 'assignee_id': wid})
    issue_id = r.json()['id']
    r = client.put(f'/api/issues/{issue_id}', headers=worker_headers, json={'status': 'processing'})
    assert r.status_code == 200, r.json()
    r = client.put(f'/api/issues/{issue_id}', headers=worker_headers, json={'title': '改名'})
    assert r.status_code == 403
    r = client.put(f'/api/issues/{issue_id}', headers=worker_headers, json={'status': 'resolved', 'resolution': '更换传感器后恢复'})
    assert r.status_code == 200, r.json()
    assert r.json()['status'] == 'resolved'

def test_issue_cancelled_status(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '可作废问题', 'issue_type': 'process'})
    issue_id = r.json()['id']
    r = client.put(f'/api/issues/{issue_id}', headers=pm_headers, json={'status': 'cancelled', 'resolution': '需求变更，不再实施'})
    assert r.status_code == 200, r.json()
    assert r.json()['status'] == 'cancelled'
    r2 = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '已解决再作废'})
    i2 = r2.json()['id']
    client.put(f'/api/issues/{i2}', headers=pm_headers, json={'status': 'resolved'})
    r3 = client.put(f'/api/issues/{i2}', headers=pm_headers, json={'status': 'cancelled'})
    assert r3.status_code == 400

def test_reporter_can_reopen_resolved_issue(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    wid = _add_worker(client, pm_headers, worker_headers, pid)
    r = client.post(f'/api/projects/{pid}/issues', headers=worker_headers, json={'title': '现场缺料', 'assignee_id': wid})
    issue_id = r.json()['id']
    client.put(f'/api/issues/{issue_id}', headers=pm_headers, json={'status': 'resolved', 'resolution': '补料完成'})
    r = client.post(f'/api/issues/{issue_id}/reopen', headers=worker_headers)
    assert r.status_code == 200, r.json()
    assert r.json()['status'] == 'open'
    pid2 = _project(client, pm_headers, '无关项目')
    _add_worker(client, pm_headers, worker_headers, pid2)
    r = client.post(f'/api/projects/{pid2}/issues', headers=pm_headers, json={'title': '第三方问题'})
    i2 = r.json()['id']
    client.put(f'/api/issues/{i2}', headers=pm_headers, json={'status': 'resolved'})
    r = client.post(f'/api/issues/{i2}/reopen', headers=worker_headers)
    assert r.status_code == 403

def test_overdue_sla_scan_notifies_pm(client, pm_headers, admin_headers):
    pid = _project(client, pm_headers)
    r = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '老问题', 'severity': 'high'})
    issue_id = r.json()['id']
    from datetime import timedelta
    from app.time_utils import utcnow
    from app.db import SessionLocal
    from app.models import Issue
    db = SessionLocal()
    try:
        i = db.get(Issue, issue_id)
        i.created_at = utcnow() - timedelta(days=4)
        db.commit()
    finally:
        db.close()
    from app.services.report_scheduler import scan_overdue_issues
    from app.db import SessionLocal as SL
    db = SL()
    try:
        result = scan_overdue_issues(db)
        db.commit()
    finally:
        db.close()
    assert result['scanned'] >= 1
    msgs = client.get('/api/notifications', headers=pm_headers).json()
    assert any(('SLA 超时' in n['title'] for n in msgs))

def _make_project_with_task(client, pm_headers, name):
    """建项目 + 生成任务，返回 (project_id, 首个任务 id)。"""
    r = client.post('/api/projects', headers=pm_headers, json={'name': name, 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'})
    assert r.status_code == 200, r.text
    pid = r.json()['id']
    r = client.post(f'/api/projects/{pid}/vehicles', headers=pm_headers, json={'vehicle_type': '潜伏式', 'model_name': 'AGV-500', 'quantity': 1})
    assert r.status_code == 200, r.text
    r = client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': ['mod-03']})
    assert r.status_code == 200, r.text
    tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    tid = tree[0]['modules'][0]['tasks'][0]['id']
    return (pid, tid)

def test_issue_create_rejects_task_from_other_project(client, pm_headers):
    pid_a, _ = _make_project_with_task(client, pm_headers, '跨项目约束-A')
    _, tid_b = _make_project_with_task(client, pm_headers, '跨项目约束-B')
    r = client.post(f'/api/projects/{pid_a}/issues', headers=pm_headers, json={'title': '跨项目任务上报', 'severity': 'high', 'task_id': tid_b})
    assert r.status_code == 400, r.json()
    assert '不属于该项目' in r.json()['detail']

def test_issue_create_rejects_unknown_task(client, pm_headers):
    pid, _ = _make_project_with_task(client, pm_headers, '悬空任务项目')
    r = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '悬空任务上报', 'severity': 'medium', 'task_id': 'no-such-task-xyz'})
    assert r.status_code == 400, r.json()
    assert '任务不存在' in r.json()['detail']

def test_issue_import_rejects_task_from_other_project(client, pm_headers):
    pid_a, _ = _make_project_with_task(client, pm_headers, '导入约束-A')
    _, tid_b = _make_project_with_task(client, pm_headers, '导入约束-B')
    r = client.post(f'/api/projects/{pid_a}/issues/import', headers=pm_headers, json={'items': [{'title': '跨项目导入', 'severity': 'low', 'task_id': tid_b}]})
    assert r.status_code == 400, r.json()
    assert '不属于该项目' in r.json()['detail']

def test_issue_import_accepts_own_project_task(client, pm_headers):
    """对照组：同项目 task_id 应正常通过，避免过度收紧。"""
    pid, tid = _make_project_with_task(client, pm_headers, '同项目导入')
    r = client.post(f'/api/projects/{pid}/issues/import', headers=pm_headers, json={'items': [{'title': '本任务问题', 'severity': 'low', 'task_id': tid}]})
    assert r.status_code == 200, r.json()
    issues = client.get(f'/api/projects/{pid}/issues', headers=pm_headers).json()
    assert len([i for i in issues if i['title'] == '本任务问题']) == 1

def _import_persistence_state(db, pid, uuids):
    """返回 (台账数, 审计数, 经理通知数, outbox 数)——供导入副作用回归断言。"""
    from app.models import ChangeLog, Notification, NotificationOutbox, Issue, Project
    project = db.get(Project, pid)
    assert project is not None and project.manager is not None
    mgr_id = project.manager
    return (db.query(Issue).filter(Issue.project_id == pid, Issue.client_uuid.in_(uuids)).count(), db.query(ChangeLog).filter(ChangeLog.project_id == pid, ChangeLog.entity_type == 'issue', ChangeLog.action == 'import').count(), db.query(Notification).filter(Notification.user_id == mgr_id, Notification.project_id == pid, Notification.ntype == 'issue_reported').count(), db.query(NotificationOutbox).filter(NotificationOutbox.user_id == mgr_id, NotificationOutbox.project_id == pid, NotificationOutbox.ntype == 'issue_reported').count())

def test_issue_import_persists_audit_notification_outbox(client, pm_headers, admin_headers):
    """导入成功后，台账 + ChangeLog(action='import') + 经理 issue_reported + outbox 全部落库。

    回归背景（研究生 REJECT / 博士确认）：曾把 db.commit() 移到 log_change/notify 之前
    且其后不再 commit，而 get_db 请求结束仅 close() 回滚未提交行——接口返回成功但审计/
    通知/outbox 全为 0。此处用非经理（admin）导入 pm 的项目，确保经理通知分支被覆盖。
    """
    from app.db import SessionLocal
    pid, _ = _make_project_with_task(client, pm_headers, '导入留痕项目')
    uuids = ['h99-imp-side-a', 'h99-imp-side-b']
    body = {'items': [{'title': '导入问题A', 'severity': 'high', 'client_uuid': uuids[0]}, {'title': '导入问题B', 'severity': 'low', 'client_uuid': uuids[1]}]}
    r = client.post(f'/api/projects/{pid}/issues/import', headers=admin_headers, json=body)
    assert r.status_code == 200, r.json()
    assert r.json()['count'] == 2
    db = SessionLocal()
    try:
        n_issues, n_audit, n_notif, n_outbox = _import_persistence_state(db, pid, uuids)
    finally:
        db.close()
    assert n_issues == 2
    assert n_audit == 1, f"ChangeLog(action='import') 未持久化（{n_audit}）"
    assert n_notif == 1, f'经理 issue_reported 通知未持久化（{n_notif}）'
    assert n_outbox == 1, f'NotificationOutbox 未持久化（{n_outbox}）'

def test_issue_import_retry_same_client_uuid_no_duplicate_side_effects(client, pm_headers, admin_headers):
    """相同 client_uuid 全量重试返回 count=0，且不重复建台账/审计/通知/outbox。"""
    from app.db import SessionLocal
    pid, _ = _make_project_with_task(client, pm_headers, '导入幂等项目')
    uuids = ['h99-imp-retry-a', 'h99-imp-retry-b']
    body = {'items': [{'title': '导入问题A', 'severity': 'high', 'client_uuid': uuids[0]}, {'title': '导入问题B', 'severity': 'low', 'client_uuid': uuids[1]}]}
    url = f'/api/projects/{pid}/issues/import'
    r1 = client.post(url, headers=admin_headers, json=body)
    assert r1.status_code == 200, r1.json()
    assert r1.json()['count'] == 2
    db = SessionLocal()
    try:
        before = _import_persistence_state(db, pid, uuids)
    finally:
        db.close()
    assert before[0] == 2 and before[1] == 1 and (before[2] == 1) and (before[3] == 1)
    r2 = client.post(url, headers=admin_headers, json=body)
    assert r2.status_code == 200, r2.json()
    assert r2.json()['count'] == 0
    db = SessionLocal()
    try:
        after = _import_persistence_state(db, pid, uuids)
    finally:
        db.close()
    assert after == before, f'重试产生了重复副作用：{before} -> {after}'

def test_issue_same_client_uuid_sequential_idempotent(client, pm_headers):
    pid, _ = _make_project_with_task(client, pm_headers, '幂等项目')
    body = {'title': '同键问题', 'severity': 'medium', 'client_uuid': 'h99-dup-uuid-01'}
    r1 = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json=body)
    r2 = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json=body)
    assert r1.status_code == 200, r1.json()
    assert r2.status_code == 200, r2.json()
    assert r1.json()['id'] == r2.json()['id']
    issues = client.get(f'/api/projects/{pid}/issues', headers=pm_headers).json()
    assert len([i for i in issues if i['id'] == r1.json()['id']]) == 1

def test_issue_client_uuid_db_unique_violation(client, pm_headers):
    """DB 层唯一约束真实存在：绕开路由预检直接插重键 → IntegrityError，不是静默重复。"""
    pid, _ = _make_project_with_task(client, pm_headers, '唯一约束项目')
    from app.db import SessionLocal
    from app.models import Issue, User
    db = SessionLocal()
    try:
        reporter = db.query(User).filter(User.username == 'admin').first()
        assert reporter is not None
        uid = reporter.id
        db.add(Issue(project_id=pid, title='第一', reporter_id=uid, issue_type='other', severity='low', client_uuid='h99-db-uuid-01'))
        db.commit()
        db.add(Issue(project_id=pid, title='第二', reporter_id=uid, issue_type='other', severity='low', client_uuid='h99-db-uuid-01'))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()

def test_issue_client_uuid_scoped_to_project(client, pm_headers):
    """同 client_uuid 允许出现在不同项目（约束是 (project_id, client_uuid)，不是全局唯一）。"""
    pid_a, _ = _make_project_with_task(client, pm_headers, '项目A')
    pid_b, _ = _make_project_with_task(client, pm_headers, '项目B')
    body = {'title': '跨项目同键', 'severity': 'medium', 'client_uuid': 'h99-cross-uuid-01'}
    r1 = client.post(f'/api/projects/{pid_a}/issues', headers=pm_headers, json=body)
    r2 = client.post(f'/api/projects/{pid_b}/issues', headers=pm_headers, json=body)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()['id'] != r2.json()['id']
