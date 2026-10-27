"""旧软删与不可变归档的只读保全及访问权限。"""

from tests.lifecycle_helpers import versioned
from datetime import timedelta
from app.time_utils import utcnow

def test_recycle_retention_never_auto_purges(client, pm_headers, admin_headers):
    """#85：旧软删和新回收站项目均不再自动物理清理。"""
    from app.db import SessionLocal
    from app.models import Project, ChangeLog
    pid = client.post('/api/projects', headers=pm_headers, json={'name': '清理项目', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}).json()['id']
    from tests.legacy_project_deletion import legacy_soft_delete
    legacy_soft_delete(client, pm_headers, pid)
    from app.services.report_scheduler import purge_soft_deleted_projects
    db = SessionLocal()
    try:
        result = purge_soft_deleted_projects(db, retention_days=30)
        db.commit()
        assert result['purged'] == 0
        assert db.get(Project, pid) is not None
        db.query(Project).filter(Project.id == pid).update({'deleted_at': utcnow() - timedelta(days=31)})
        db.commit()
        result = purge_soft_deleted_projects(db, retention_days=30)
        db.commit()
        assert result['purged'] == 0 and result['disabled']
        assert db.get(Project, pid) is not None
        purge_logs = db.query(ChangeLog).filter(ChangeLog.action == 'delete_purge').all()
        assert len(purge_logs) == 0
    finally:
        db.close()

def _soft_delete_project(client, admin_headers, pm_headers, pid):
    from tests.legacy_project_deletion import legacy_soft_delete
    legacy_soft_delete(client, pm_headers, pid)

def test_legacy_immutable_archive_remains_readable_without_new_automatic_purge(client, admin_headers, pm_headers, worker_headers):
    """T008：物理清理前归档快照+全量审计链；清理后按原 project_id 可查、校验哈希匹配、普通用户无权限。"""
    from app.db import SessionLocal
    from app.models import Project, ProjectArchive
    from app.services.report_scheduler import purge_soft_deleted_projects
    pid = client.post('/api/projects', headers=pm_headers, json={'name': '归档审计项目', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}).json()['id']
    client.post(f'/api/projects/{pid}/vehicles', headers=pm_headers, json={'vehicle_type': '潜伏式', 'model_name': 'AGV-500', 'quantity': 2})
    client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': ['mod-03']})
    client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'client': '归档客户'}))
    # Construct a real pre-v3 module source in addition to current flat work.
    from app.models import Phase, Module, Task
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='旧实施阶段'); db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='原模块说明'); db.add(module); db.flush()
        db.add(Task(project_id=pid, module_id=module.id, name='旧工作原件', quantity_type='fixed', target_quantity=2.5, unit='套'))
        db.commit()
    _soft_delete_project(client, admin_headers, pm_headers, pid)
    db = SessionLocal()
    try:
        from datetime import timedelta
        from app.time_utils import utcnow
        db.query(Project).filter(Project.id == pid).update({'deleted_at': utcnow() - timedelta(days=31)})
        db.commit()
        result = purge_soft_deleted_projects(db, retention_days=30)
        db.commit()
        assert result['purged'] == 0
        assert db.get(Project, pid) is not None
        from tests.legacy_project_deletion import legacy_archive_snapshot
        legacy_archive_snapshot(db, db.get(Project, pid))
        db.delete(db.get(Project, pid))
        db.commit()
        arch = db.query(ProjectArchive).filter(ProjectArchive.project_id == pid).first()
        assert arch is not None, '清理后应留下不可变归档'
        assert arch.project_name == '归档审计项目'
        assert arch.snapshot['project']['name'] == '归档审计项目'
        assert arch.snapshot['modules'], '快照应含任务模块'
        assert arch.change_logs, '归档应含全量 change_logs'
        assert arch.checksum and len(arch.checksum) == 64
        assert any((c['operator_id'] for c in arch.change_logs)), '审计链应含操作者'
    finally:
        db.close()
    # 系统管理员的元数据读取权不自动授予原负责人的保密资料。
    assert client.get(f'/api/archives/projects/{pid}', headers=admin_headers).status_code == 403
    from app.models import User
    owner_id = client.get('/api/auth/me', headers=pm_headers).json()['id']
    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        owner.permission_overrides = {**(owner.permission_overrides or {}), 'system.archives.read': True}
        db.commit()
    full = client.get(f'/api/archives/projects/{pid}', headers=pm_headers)
    assert full.status_code == 200
    body = full.json()
    assert body['project_id'] == pid
    assert body['snapshot']['project']['name'] == '归档审计项目'
    assert body['change_logs'], '有归档读取权的原负责人应能读取完整审计链'
    assert body['checksum']
    verify = client.get(f'/api/archives/projects/{pid}/verify', headers=admin_headers)
    assert verify.status_code == 200 and verify.json()['match'] is True
    listing = client.get('/api/archives/projects', headers=admin_headers)
    assert listing.status_code == 200
    assert any((item['project_id'] == pid for item in listing.json()))
    assert client.get(f'/api/archives/projects/{pid}', headers=worker_headers).status_code == 403
