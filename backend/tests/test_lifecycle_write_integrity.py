"""生命周期证据写入与归档锁后复核。"""

from datetime import date
import pytest
from fastapi import HTTPException
from app.db import SessionLocal
from app.models import AcceptanceRecord, ArchiveChecklist, CheckItem, DailyProgress, Module, Phase, Project, ProjectPreparationItem, ProjectReadinessReview, Task, User
from tests.test_project_lifecycle_boundaries import project


def check_version(cid):
    with SessionLocal() as db:
        return db.get(CheckItem, cid).version or 0


def completeable_project(client, headers, *, documents_data=None, legacy_acceptance=False):
    pid = project(client, headers, '端到端生命周期')
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = 'acceptance'
        phase = Phase(project_id=pid, name='现场实施')
        db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='现场工作')
        db.add(module); db.flush()
        task = Task(project_id=pid, phase_id=phase.id, module_id=module.id, name='安全调试',
                    quantity_type='fixed', target_quantity=1)
        db.add(task); db.flush()
        check = CheckItem(project_id=pid, task_id=task.id, name='安全保护', is_safety_critical=True,
                          is_required=True, is_applicable=True, is_done=True)
        db.add(check)
        db.add(DailyProgress(project_id=pid, task_id=task.id, user_id=p.manager,
                             work_date=date(2026, 9, 30), completed_quantity=1,
                             client_uuid='round6-completeable'))
        if legacy_acceptance:
            db.add(AcceptanceRecord(project_id=pid, accepted_by_name='客户代表',
                                   accepted_at=date(2026, 9, 30), conclusion='accepted'))
        for row in db.query(ArchiveChecklist).filter_by(project_id=pid):
            row.is_done = True
        db.commit()
        ids = pid, task.id, check.id
    from tests.lifecycle_helpers import complete_vehicle_progress
    complete_vehicle_progress(client, headers, pid)
    completed = client.put(f'/api/projects/{pid}/work-items/{ids[1]}/completion', headers=headers,
        json={'version': 0, 'is_completed': True, 'reason': '已按现行工作口径核对并完成'})
    assert completed.status_code == 200, completed.text
    from tests.document_helpers import complete_documents, requirement, upload_documents
    from tests.lifecycle_helpers import register_kickoff
    register_kickoff(client, headers, pid)
    complete_documents(client, headers, pid)
    for index, item in enumerate(documents_data or []):
        item = {'name': item, 'required': True} if isinstance(item, str) else item
        row = requirement(client, headers, pid, name=item['name'], code=f'6.99.{index + 1}', required=item.get('required', True), note=item.get('description') or item.get('note') or '')
        if item.get('done'):
            upload_documents(client, headers, pid, [row['id']])
    if not legacy_acceptance:
        from tests.lifecycle_helpers import sign_current_scope
        sign_current_scope(client, headers, pid)
    return ids


def test_optional_document_does_not_prevent_completion(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers, documents_data=[
        {'name': '选填补充照片', 'required': False, 'done': False},
        {'name': '必需报告', 'required': True, 'done': True, 'status': 'approved'},
    ])
    result = client.post(f'/api/projects/{pid}/status', headers=pm_headers,
                         json={'status': 'completed'})
    assert result.status_code == 200, result.text


def test_required_document_needs_real_submission_for_completion(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers, documents_data=['必需报告'])
    result = client.post(f'/api/projects/{pid}/status', headers=pm_headers,
                         json={'status': 'completed'})
    assert result.status_code == 400, result.text
    assert '资料' in result.json()['detail']['message']


@pytest.mark.parametrize('state', ['pending', 'failed', 'na'])
def test_retracted_preparation_clears_completion_metadata(client, pm_headers, state):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    created = client.post(path, headers=pm_headers, json={'name': '网络核查'}).json()
    assert client.put(path + '/' + created['id'], headers=pm_headers,
                      json={'status': 'passed'}).status_code == 200
    changed = client.put(path + '/' + created['id'], headers=pm_headers, json={'status': state})
    assert changed.status_code == 200, changed.text
    with SessionLocal() as db:
        row = db.get(ProjectPreparationItem, created['id'])
        assert row.actual_date is None
        assert row.completed_by is None
        assert row.completed_at is None


@pytest.mark.parametrize('operation', ['create', 'update'])
def test_preparation_pass_records_actor_even_with_explicit_actual_date(client, pm_headers, operation):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    payload = {'name': '检查完成', 'status': 'passed', 'actual_date': '2026-09-29'}
    if operation == 'create':
        result = client.post(path, headers=pm_headers, json=payload)
    else:
        created = client.post(path, headers=pm_headers, json={'name': '检查完成'}).json()
        result = client.put(path + '/' + created['id'], headers=pm_headers, json=payload)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        row = db.get(ProjectPreparationItem, result.json()['id'])
        assert row.actual_date == date(2026, 9, 29)
        assert row.completed_by == db.get(Project, pid).manager
        assert row.completed_at is not None


@pytest.mark.parametrize('operation', ['create', 'update', 'delete', 'import'])
def test_preparation_write_rechecks_archival_after_preload(client, pm_headers, operation):
    from app.routers import preparations as prep
    pid = project(client, pm_headers)
    assert client.post(f'/api/projects/{pid}/procurements', headers=pm_headers, json={'name': '采购核查', 'category': 'procurement'}).status_code == 200
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, p.manager)
        item = stale.query(ProjectPreparationItem).filter_by(project_id=pid).first()
        count = stale.query(ProjectPreparationItem).filter_by(project_id=pid).count()
        with SessionLocal() as newer:
            newer.get(Project, pid).status = 'archived'
            newer.commit()
        with pytest.raises(HTTPException) as error:
            if operation == 'create':
                prep.create_item(pid, prep.PrepItemCreate(name='归档后新增'), actor, stale)
            elif operation == 'update':
                prep.update_item(pid, item.id, prep.PrepItemUpdate(name='归档后改名'), actor, stale)
            elif operation == 'delete':
                prep.delete_item(pid, item.id, actor, stale)
            elif operation == 'seed':
                prep.seed_items(pid, actor, stale)
            else:
                prep.import_procurements(pid, prep.ProcurementImportBody(), actor, stale)
        assert error.value.status_code == 400
        stale.rollback()
    with SessionLocal() as db:
        assert db.query(ProjectPreparationItem).filter_by(project_id=pid).count() == count
        assert db.query(ProjectReadinessReview).filter_by(project_id=pid).count() == 0


@pytest.mark.parametrize('operation', ['acceptance'])
def test_completion_evidence_rechecks_archival_after_preload(client, pm_headers, operation):
    from app.routers.projects import create_acceptance, AcceptanceCreate
    pid = project(client, pm_headers)
    with SessionLocal() as setup:
        setup.get(Project, pid).status = 'completed'
        setup.commit()
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, p.manager)
        item = stale.query(ArchiveChecklist).filter_by(project_id=pid).first()
        with SessionLocal() as newer:
            newer.get(Project, pid).status = 'archived'
            newer.commit()
        with pytest.raises(HTTPException) as error:
            if operation == 'acceptance':
                create_acceptance(pid, AcceptanceCreate(accepted_by_name='客户', accepted_at=date(2026, 9, 30)), actor, p, stale)
        assert error.value.status_code == 400
        stale.rollback()
    with SessionLocal() as db:
        assert db.query(AcceptanceRecord).filter_by(project_id=pid).count() == 0
        assert not db.query(ArchiveChecklist).filter_by(project_id=pid, is_done=True).count()


def test_repair_after_failed_archive_gate_can_finish_normally(client, pm_headers):
    pid, _, cid = completeable_project(client, pm_headers)
    status_path = f'/api/projects/{pid}/status'
    assert client.post(status_path, headers=pm_headers, json={'status': 'completed'}).status_code == 200
    # Checks are frozen once completed: reopen to acceptance before recording a failed recheck.
    assert client.post(status_path, headers=pm_headers, json={'status': 'acceptance'}).status_code == 200
    assert client.put(f'/api/projects/{pid}/check-items/{cid}', headers=pm_headers,
                      json={'failed': True, 'failed_reason': '复检不通过', 'version': check_version(cid)}).status_code == 200
    assert client.post(status_path, headers=pm_headers, json={'status': 'completed'}).status_code == 400
    # The denial must not strand the project: repair, complete, then archive.
    assert client.put(f'/api/projects/{pid}/check-items/{cid}', headers=pm_headers,
                      json={'is_done': True, 'version': check_version(cid)}).status_code == 200
    assert client.post(status_path, headers=pm_headers, json={'status': 'completed'}).status_code == 200
    assert client.post(status_path, headers=pm_headers,
                       json={'status': 'archived', 'retrospective': '整改复检通过后归档'}).status_code == 200


@pytest.mark.parametrize('prior', ['preparing'])
def test_pausing_pre_execution_project_does_not_enable_acceptance(client, pm_headers, prior):
    pid = project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).status = prior
        db.commit()
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers,
                       json={'status': 'suspended', 'reason': '准备延期'}).status_code == 200
    result = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers,
                         json={'accepted_by_name': '客户', 'accepted_at': '2026-09-30'})
    assert result.status_code == 400, result.text


def test_whitespace_is_not_acceptance_signer(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers)
    result = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers,
                         json={'accepted_by_name': '  ', 'accepted_at': '2026-09-30'})
    assert result.status_code in (400, 422), result.text


def test_legacy_archive_can_reopen_for_correction_without_recertifying_completion(client, pm_headers):
    pid, _, cid = completeable_project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).status = 'archived'
        check = db.get(CheckItem, cid)
        check.is_done = False
        check.failed = True
        check.failed_reason = '旧档案存在未修复安全问题'
        db.query(AcceptanceRecord).filter_by(project_id=pid).delete()
        db.commit()
    path = f'/api/projects/{pid}/status'
    restored = client.post(path, headers=pm_headers, json={'status': 'completed'})
    assert restored.status_code == 200, restored.text
    # Restoration is not a fresh completion or a route around archive checks.
    blocked = client.post(path, headers=pm_headers,
                          json={'status': 'archived', 'retrospective': '仍然缺少复检'})
    assert blocked.status_code == 400, blocked.text
    assert client.post(path, headers=pm_headers, json={'status': 'acceptance'}).status_code == 200
    assert client.put(f'/api/projects/{pid}/check-items/{cid}', headers=pm_headers,
                      json={'is_done': True, 'version': check_version(cid)}).status_code == 200
    missing_signature = client.post(path, headers=pm_headers, json={'status': 'completed'})
    assert missing_signature.status_code == 400 and '验收' in missing_signature.json()['detail']['message']
    with SessionLocal() as db:
        assert db.query(AcceptanceRecord).filter_by(project_id=pid).count() == 0


@pytest.mark.parametrize('kind', ['preparation', 'documents', 'acceptance'])
def test_evidence_write_rechecks_revoked_capability_after_preload(client, admin_headers, worker_headers, kind):
    from app.routers import preparations as prep
    from app.routers.project_documents import create_requirement, RequirementInput
    from app.routers.projects import create_acceptance, AcceptanceCreate
    pid = project(client, admin_headers)
    worker = client.get('/api/auth/me', headers=worker_headers).json()['id']
    capability = {'preparation': 'project.manage_plan', 'documents': 'project.manage_plan', 'acceptance': 'project.update'}[kind]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = 'preparing'
        p.members = [*p.members, worker]
        p.member_permissions = [{'user_id': worker, 'capabilities': [capability]}]
        db.commit()
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, worker)
        with SessionLocal() as newer:
            newer.get(Project, pid).member_permissions = []
            newer.commit()
        with pytest.raises(HTTPException) as error:
            if kind == 'preparation':
                prep.create_item(pid, prep.PrepItemCreate(name='被撤销权限后新增'), actor, stale)
            elif kind == 'documents':
                create_requirement(pid, RequirementInput(stage_key='6', code='6.99', name='被撤销后新增资料', scope='project', timing_type='on_demand'), actor, stale)
            else:
                create_acceptance(pid, AcceptanceCreate(accepted_by_name='客户', accepted_at=date(2026, 9, 30)), actor, p, stale)
        assert error.value.status_code == 403
        stale.rollback()


def test_archive_rechecks_required_document_withdrawn_after_completion(client, pm_headers):
    from tests.document_helpers import documents
    pid, _, _ = completeable_project(client, pm_headers)
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'completed'}).status_code == 200
    row = next(row for row in documents(client, pm_headers, pid)['documents'] if row['required'] and row['stage_key'] in ('4', '5', '6', '7'))
    withdrawn = client.put(f'/api/projects/{pid}/documents/{row["id"]}', headers=pm_headers,
        json={'status': 'pending', 'reason': '归档前发现附件需要补充', 'version': row['version']})
    assert withdrawn.status_code == 200, withdrawn.text
    result = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'archived', 'retrospective': '收尾复盘'})
    assert result.status_code == 400 and '资料' in result.json()['detail']['message']
    with SessionLocal() as db:
        assert db.get(Project, pid).status == 'completed'


def test_retired_transfer_request_cannot_duplicate_preserved_history(client, pm_headers, admin_headers):
    """旧创建入口与审批算法已移除；重复调用也不改写原申请或通知。"""
    from app.models import ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog
    pid = project(client, pm_headers)
    actor = client.get('/api/auth/me', headers=pm_headers).json()['id']
    target = client.get('/api/auth/me', headers=admin_headers).json()['id']
    with SessionLocal() as db:
        source = ProjectGovernanceRequest(project_id=pid, project_name='原始项目名称', requested_by=actor,
            source_manager_id=actor, target_manager_id=target, request_type='transfer',
            reason='原岗位调整申请', status='pending', review_note='完整保留原审核说明')
        db.add(source); db.commit(); identity=source.id
        before = tuple(getattr(source, column.name) for column in source.__table__.columns)
        counts = tuple(db.query(model).filter_by(project_id=pid).count()
            for model in (ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog))
    for _ in range(2):
        response = client.post(f'/api/projects/{pid}/governance-requests', headers=pm_headers,
            json={'request_type': 'transfer', 'target_manager_id': target, 'reason': '重复的旧申请操作'})
        assert response.status_code == 410, response.text
    with SessionLocal() as db:
        source=db.get(ProjectGovernanceRequest, identity)
        assert tuple(getattr(source, column.name) for column in source.__table__.columns) == before
        assert tuple(db.query(model).filter_by(project_id=pid).count()
            for model in (ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog)) == counts


def test_retired_transfer_request_cannot_restore_previous_manager_authority(client, pm_headers, admin_headers):
    """旧负责人保留旧页面也不能通过退役审批入口生成另一条事实。"""
    from app.models import ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog
    pid = project(client, pm_headers)
    target = client.get('/api/auth/me', headers=admin_headers).json()['id']
    with SessionLocal() as db:
        row=db.get(Project, pid); row.manager=target; db.commit(); version=row.version
        counts=tuple(db.query(model).filter_by(project_id=pid).count()
            for model in (ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog))
    response = client.post(f'/api/projects/{pid}/governance-requests', headers=pm_headers,
        json={'request_type': 'transfer', 'target_manager_id': target, 'reason': '已失效的旧负责人页面'})
    assert response.status_code == 410, response.text
    with SessionLocal() as db:
        row=db.get(Project, pid)
        assert row.manager == target and row.version == version
        assert tuple(db.query(model).filter_by(project_id=pid).count()
            for model in (ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog)) == counts


@pytest.mark.parametrize('kind', ['transfer', 'delete'])
def test_retired_governance_cannot_forge_requester_or_notify_reviewers(client, pm_headers, worker_headers, kind):
    from app.models import ProjectGovernanceRequest, Notification, NotificationOutbox, ChangeLog
    pid = project(client, pm_headers)
    worker_id = client.get('/api/auth/me', headers=worker_headers).json()['id']
    manager_id = client.get('/api/auth/me', headers=pm_headers).json()['id']
    from tests.lifecycle_helpers import project_version
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json={'members': [worker_id], 'version': project_version(client, pm_headers, pid)}).status_code == 200
    with SessionLocal() as db:
        count=db.query(ChangeLog).filter_by(project_id=pid).count()
    response = client.post(f'/api/projects/{pid}/governance-requests', headers=worker_headers,
        json={'request_type': kind, 'reason': '冒用项目负责人的申请',
            'requested_by': manager_id, 'source_manager_id': manager_id})
    assert response.status_code == 410, response.text
    with SessionLocal() as db:
        assert not db.query(ProjectGovernanceRequest).filter_by(project_id=pid).count()
        assert not db.query(Notification).filter_by(project_id=pid, ntype='governance').count()
        assert not db.query(NotificationOutbox).filter_by(project_id=pid, ntype='governance').count()
        assert db.query(ChangeLog).filter_by(project_id=pid).count() == count
