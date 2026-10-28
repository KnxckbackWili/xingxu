"""项目参与者校验、人工阶段权限与直接移交。"""
from tests.lifecycle_helpers import versioned



def test_create_project_bad_manager_id_returns_400(client, pm_headers):
    r = client.post('/api/projects', headers=pm_headers, json={'name': '坏负责人', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30', 'manager_id': 'no-such-user'})
    assert r.status_code == 400
    assert '项目经理' in r.json()['detail']

def _project(client, pm_headers, name='功能边界项目'):
    r = client.post('/api/projects', headers=pm_headers, json={'name': name, 'start_date': '2026-08-10', 'status': 'preparing', 'new_vehicles': False, 'end_date': '2026-09-30'})
    assert r.status_code == 200, r.json()
    return r.json()['id']

def test_update_project_bad_member_id_returns_400(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': ['no-such-user']}))
    assert r.status_code == 400
    assert '成员' in r.json()['detail']

def test_direct_transfer_bad_recipient_returns_400(client, admin_headers, pm_headers):
    pid = _project(client, pm_headers)
    preview = client.get(f'/api/projects/{pid}/transfer-preview', headers=admin_headers)
    assert preview.status_code == 200, preview.text
    result = client.post(f'/api/projects/{pid}/transfer', headers=admin_headers, json={
        'target_manager_id': 'no-such-user', 'reason': '核对接收人仍真实存在且可接手',
        'version': preview.json()['version'],
        'member_removal_confirmations': [row['user_id'] for row in preview.json()['removed']]})
    assert result.status_code == 400
    assert '项目经理' in result.json()['detail']

def test_director_can_change_status(client, admin_headers, pm_headers):
    from tests.document_helpers import documents, upload_documents
    pid = _project(client, pm_headers)
    rows = documents(client, pm_headers, pid)['documents']
    required = [row['id'] for row in rows if row['stage_key'] == '4' and row['required'] and row['applicable']]
    assert required
    upload_documents(client, pm_headers, pid, required)
    result = client.post('/api/users', headers=admin_headers, json={
        'username': 'dir1', 'password': 'Review123!', 'display_name': '总监一号', 'role': 'director'})
    assert result.status_code == 200, result.text
    login = client.post('/api/auth/login', json={'username': 'dir1', 'password': 'Review123!'})
    assert login.status_code == 200, login.text
    director = {'Authorization': 'Bearer ' + login.json()['access_token']}
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    result = client.post(f'/api/projects/{pid}/status', headers=director, json={'status': 'executing'})
    assert result.status_code == 200, result.text
    assert client.get(f'/api/projects/{pid}', headers=director).json()['status'] == 'executing'

def test_retired_transfer_request_does_not_notify_or_mutate(client, pm_headers, admin_headers):
    """退役申请入口不得创建审批事实或通知；直接移交另有正向覆盖。"""
    from app.db import SessionLocal
    from app.models import Project, ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog
    pid = _project(client, pm_headers)
    target = _create_user(client, admin_headers, 'notification-receiver')
    def snapshot():
        with SessionLocal() as db:
            project = db.get(Project, pid)
            return (project.manager, project.version, list(project.members),
                db.query(ProjectGovernanceRequest).filter_by(project_id=pid).count(),
                db.query(Notification).filter_by(project_id=pid).count(),
                db.query(NotificationOutbox).filter_by(project_id=pid).count(),
                db.query(ChangeLog).filter_by(project_id=pid).count())
    before = snapshot()
    result = client.post(f'/api/projects/{pid}/governance-requests', headers=pm_headers,
        json={'request_type': 'transfer', 'target_manager_id': target, 'reason': '岗位调整，验证通知及时到达'})
    assert result.status_code == 410, result.text
    assert snapshot() == before

def _login(client, username):
    response = client.post('/api/auth/login', json={'username': username, 'password': 'password123'})
    return {'Authorization': f'Bearer {response.json()['access_token']}'}

def _transfer(client, admin_headers, pid, target_id, requester_headers):
    preview = client.get(f'/api/projects/{pid}/transfer-preview', headers=admin_headers)
    assert preview.status_code == 200, preview.text
    transferred = client.post(f'/api/projects/{pid}/transfer', headers=admin_headers, json={
        'target_manager_id': target_id, 'reason': '岗位调整，已完成风险交底',
        'version': preview.json()['version'],
        'member_removal_confirmations': [row['user_id'] for row in preview.json()['removed']]})
    assert transferred.status_code == 200, transferred.text
    return transferred.json()

def _managed_project(client, headers, name, manager_id=None):
    body = {'name': name, 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}
    if manager_id:
        body['manager_id'] = manager_id
    r = client.post('/api/projects', headers=headers, json=body)
    assert r.status_code == 200, r.json()
    return r.json()['id']

def _create_user(client, admin_headers, username, role='pm'):
    response = client.post('/api/users', headers=admin_headers, json={'username': username, 'password': 'password123', 'display_name': username, 'role': role})
    assert response.status_code == 200, response.text
    return response.json()['id']

def test_transfer_removes_old_manager_without_explicit_role(client, admin_headers):
    """T007：旧负责人无其他显式角色 → 从 members 与 project_members 同时移除且无法再读取项目。"""
    oldpm = _create_user(client, admin_headers, 'oldpm')
    newpm = _create_user(client, admin_headers, 'newpm')
    old_headers = _login(client, 'oldpm')
    pid = _managed_project(client, old_headers, '移交移除项目', manager_id=oldpm)
    assert oldpm in client.get(f'/api/projects/{pid}', headers=old_headers).json()['members']
    _transfer(client, admin_headers, pid, newpm, old_headers)
    assert client.get(f'/api/projects/{pid}', headers=old_headers).status_code == 404
    from app.db import SessionLocal
    from app.models import Project, ProjectMember
    db = SessionLocal()
    try:
        p = db.get(Project, pid)
        assert oldpm not in (p.members or []), '旧负责人应从 members 移除'
        rows = db.query(ProjectMember).filter(ProjectMember.project_id == pid, ProjectMember.user_id == oldpm).all()
        assert rows == [], '旧负责人应从 project_members 移除'
        from app.models import ChangeLog
        transfer_logs = db.query(ChangeLog).filter(ChangeLog.project_id == pid, ChangeLog.action == 'transfer').all()
        assert any((t.new_value.get('manager') == newpm for t in transfer_logs))
    finally:
        db.close()
    assert client.get(f'/api/projects/{pid}', headers=_login(client, 'newpm')).status_code == 200

def test_transfer_keeps_old_manager_when_technical_manager(client, admin_headers):
    """T007：旧负责人同时是技术负责人 → 保留成员权限，仍可读取项目。"""
    oldpm = _create_user(client, admin_headers, 'oldpm2')
    newpm = _create_user(client, admin_headers, 'newpm2')
    old_headers = _login(client, 'oldpm2')
    pid = _managed_project(client, old_headers, '移交保留技术项目', manager_id=oldpm)
    r = client.put(f'/api/projects/{pid}', headers=old_headers, json=versioned(pid, {'technical_manager_id': oldpm}))
    assert r.status_code == 200, r.json()
    _transfer(client, admin_headers, pid, newpm, old_headers)
    assert client.get(f'/api/projects/{pid}', headers=old_headers).status_code == 200
    detail = client.get(f'/api/projects/{pid}', headers=old_headers).json()
    assert oldpm in (detail['members'] or [])

def test_transfer_keeps_old_manager_when_co_manager(client, admin_headers):
    """T007：旧负责人持有有效协管授权 → 保留成员权限，仍可读取项目。

    API 不允许 manager 兼任协管（projects.py 校验 grant.user_id == p.manager 时跳过），
    因此该状态只能经 DB 注入，用于验证移交保留规则的防御性路径。
    """
    oldpm = _create_user(client, admin_headers, 'oldpm3')
    newpm = _create_user(client, admin_headers, 'newpm3')
    old_headers = _login(client, 'oldpm3')
    pid = _managed_project(client, old_headers, '移交保留协管项目', manager_id=oldpm)
    from app.db import SessionLocal
    from app.models import Project
    db = SessionLocal()
    try:
        p = db.get(Project, pid)
        p.co_managers = [{'user_id': oldpm, 'expires_at': None}]
        p.members = list(set((p.members or []) + [oldpm]))
        db.commit()
    finally:
        db.close()
    _transfer(client, admin_headers, pid, newpm, old_headers)
    assert client.get(f'/api/projects/{pid}', headers=old_headers).status_code == 200
    detail = client.get(f'/api/projects/{pid}', headers=old_headers).json()
    assert oldpm in (detail['members'] or [])

def test_direct_transfer_preserves_daily_history_and_notifies_owners(client, admin_headers):
    """旧日程是保留来源；负责人变化不重写它，两位负责人收到通知并有审计。"""
    from datetime import date
    from app.db import SessionLocal
    from app.models import ScheduleEntry, Task, Phase, ChangeLog
    oldpm = _create_user(client, admin_headers, 'oldpm4')
    newpm = _create_user(client, admin_headers, 'newpm4')
    old_headers = _login(client, 'oldpm4')
    pid = _managed_project(client, old_headers, '移交通知项目', manager_id=oldpm)
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='实施工作'); db.add(phase); db.flush()
        task = Task(project_id=pid, phase_id=phase.id, name='历史工作', quantity_type='fixed', target_quantity=2, unit='台')
        db.add(task); db.flush()
        entry = ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2026, 8, 10), assignee_id=oldpm,
            planned_quantity=1.25, status='planned', notes='原日程说明', is_confirmed=False, version=3)
        db.add(entry); db.commit(); identity=entry.id
        before = (entry.task_id, entry.assignee_id, entry.work_date, entry.planned_quantity, entry.status, entry.notes, entry.version)
    _transfer(client, admin_headers, pid, newpm, old_headers)
    with SessionLocal() as db:
        entry = db.get(ScheduleEntry, identity)
        assert (entry.task_id, entry.assignee_id, entry.work_date, entry.planned_quantity, entry.status, entry.notes, entry.version) == before
        audit = db.query(ChangeLog).filter_by(project_id=pid, action='transfer').one()
        assert audit.old_value['manager'] == oldpm and audit.new_value['manager'] == newpm
        assert audit.operator_id == client.get('/api/auth/me', headers=admin_headers).json()['id']
    new_msgs = client.get('/api/notifications', headers=_login(client, 'newpm4')).json()
    assert any('已成为项目' in (row.get('title') or '') for row in new_msgs)
    old_msgs = client.get('/api/notifications', headers=old_headers).json()
    assert any('负责人已更换' in (row.get('title') or '') for row in old_msgs)
