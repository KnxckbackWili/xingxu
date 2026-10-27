"""工作定义及现场检查状态的完整性。"""

from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Attachment, DailyProgress, Project, Task, VehicleLifecycleEvent
from tests.test_execution_workflow_audit import _execution


def test_task_requirements_edit_cannot_forge_review_provenance(client, pm_headers):
    pid, tid, _ = _execution(client)
    changed = client.put(f'/api/projects/{pid}/tasks/{tid}', headers=pm_headers, json={'version': 0,
        'deliverables': [{'name': '客户验收单', 'required': True, 'status': 'approved', 'done': True,
                          'submitted_by': 'user-worker-001', 'review_by': 'user-admin-001',
                          'attachment_id': 'forged-file', 'review_at': '2026-09-30T00:00:00'}]})
    assert changed.status_code == 400, changed.text
    with SessionLocal() as db:
        assert not db.get(Task, tid).deliverables


def test_material_requirement_edit_preserves_submitted_snapshot_and_file(client, pm_headers, worker_headers):
    from tests.document_helpers import requirement, upload_documents, documents
    pid, _, _ = _execution(client)
    row = requirement(client, pm_headers, pid, name='签字单')
    submitted = upload_documents(client, worker_headers, pid, [row['id']])['documents'][0]
    state = documents(client, pm_headers, pid)
    definition = next(value for value in state['definitions'] if value['id'] == row['definition_id'])
    fields = ('stage_key', 'code', 'name', 'template_no', 'required', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type', 'confidential_default', 'external_visible_default', 'external_never_visible', 'sort_order', 'note')
    body = {key: definition[key] for key in fields}
    body.update(required=False, note='选填')
    result = client.put(f'/api/projects/{pid}/documents/requirements/{definition["id"]}', headers=pm_headers, json=body)
    assert result.status_code == 200, result.text
    kept = next(value for value in documents(client, pm_headers, pid)['documents'] if value['id'] == row['id'])
    assert kept['required'] is True and kept['status'] == 'submitted' and kept['versions'] == submitted['versions']
    assert result.json()['required'] is False and result.json()['note'] == '选填'


@pytest.mark.parametrize('attachment_kind', ['missing', 'other_project'])
def test_vehicle_event_attachment_must_be_current_project_evidence(client, pm_headers, attachment_kind):
    pid, _, _ = _execution(client)
    unit = client.post(f'/api/projects/{pid}/vehicle-units', headers=pm_headers, json={'asset_code': 'R6'}).json()['id']
    attachment_id = 'missing-file'
    if attachment_kind == 'other_project':
        other, _, _ = _execution(client)
        with SessionLocal() as db:
            file = Attachment(project_id=other, filename='private.pdf', stored_name='private.pdf', file_size=0)
            db.add(file); db.commit(); attachment_id = file.id
    result = client.post(f'/api/projects/{pid}/vehicle-units/{unit}/events', headers=pm_headers, json={
        'event_type': 'fault', 'event_date': date.today().isoformat(), 'title': '故障证据', 'attachment_id': attachment_id})
    assert result.status_code == 400, result.text
    with SessionLocal() as db:
        assert db.query(VehicleLifecycleEvent).filter_by(vehicle_unit_id=unit, event_type='fault').count() == 0


@pytest.mark.parametrize('target', [None, 0])
@pytest.mark.parametrize('completion', ['pending', 'na', 'manual'])
def test_unknown_quantity_must_be_resolved_before_completion(client, target, completion):
    from app.models import CheckItem
    from app.services.progress import project_completion_blocker_tasks
    pid, tid, cid = _execution(client)
    with SessionLocal() as db:
        task = db.get(Task, tid)
        task.target_quantity = target
        db.get(CheckItem, cid).is_done = True
        if completion == 'na':
            db.get(CheckItem, cid).is_applicable = False
        elif completion == 'manual':
            task.manually_completed = True
        other = Task(project_id=pid, module_id=task.module_id, name='已完成的另一任务', target_quantity=1,
                     manually_completed=True)
        db.add(other); db.commit()
        blockers = {row.id for row in project_completion_blocker_tasks(db, pid)}
        assert (tid in blockers) == (completion == 'pending')


@pytest.mark.parametrize('operation', ['create', 'edit'])
@pytest.mark.parametrize('transition', ['completed', 'archived', 'revoked'])
def test_task_plan_rechecks_lifecycle_and_permission_after_waiting(client, pm_headers, monkeypatch, operation, transition):
    from app.models import ProjectMember, Phase
    from app.services import record_lock
    pid, tid, _ = _execution(client, status='preparing')
    with SessionLocal() as db:
        phase = db.query(Phase).filter_by(project_id=pid).first()
        db.get(Task, tid).phase_id = phase.id
        db.commit()
        phase_id = phase.id
    original = record_lock.lock_record
    seen = []
    def before_lock(db, entity, **kwargs):
        if isinstance(entity, Project) and entity.id == pid and not seen:
            with SessionLocal() as other:
                project = other.get(Project, pid)
                if transition == 'revoked':
                    project.manager = 'user-admin-001'
                    other.query(ProjectMember).filter_by(project_id=pid, user_id='user-pm-001').delete()
                else:
                    project.status = transition
                other.commit()
            seen.append(True)
        return original(db, entity, **kwargs)
    monkeypatch.setattr(record_lock, 'lock_record', before_lock)
    if operation == 'create':
        result = client.post(f'/api/projects/{pid}/work-items', headers=pm_headers,
                             json={'phase_id': phase_id, 'name': '迟到新增'})
    else:
        result = client.put(f'/api/projects/{pid}/work-items/{tid}', headers=pm_headers, json={'version': 0, 'name': '迟到改名'})
    assert seen == [True]
    assert result.status_code in ((403, 404) if transition == 'revoked' else (400,)), result.text
    with SessionLocal() as db:
        assert db.get(Task, tid).name == '调试'
        assert db.query(Task).filter_by(project_id=pid).count() == 1


@pytest.mark.parametrize('withdrawal', [{'failed': False}, {'is_done': False}, {'is_done': False, 'failed': False}])
def test_check_failure_withdrawal_has_audit_and_repeat_pass_preserves_inspector(client, worker_headers, pm_headers, withdrawal):
    from app.models import ChangeLog, CheckItem
    pid, _, cid = _execution(client)
    url = f'/api/projects/{pid}/check-items/{cid}'
    failed = client.put(url, headers=worker_headers, json={'failed': True, 'failed_reason': '碰撞测试失败', 'version': 0})
    assert failed.status_code == 200, failed.text
    with SessionLocal() as db:
        before = db.query(ChangeLog).filter_by(project_id=pid, entity_id=cid).count()
    undone = client.put(url, headers=worker_headers, json={**withdrawal, 'version': failed.json()['version']})
    assert undone.status_code == 200, undone.text
    with SessionLocal() as db:
        assert db.query(ChangeLog).filter_by(project_id=pid, entity_id=cid).count() == before + 1
    passed = client.put(url, headers=worker_headers, json={'is_done': True, 'version': undone.json()['version']})
    assert passed.status_code == 200, passed.text
    with SessionLocal() as db:
        original = db.get(CheckItem, cid).done_at
    repeated = client.put(url, headers=pm_headers, json={'is_done': True, 'is_applicable': True, 'version': passed.json()['version']})
    assert repeated.status_code == 200, repeated.text
    with SessionLocal() as db:
        check = db.get(CheckItem, cid)
        assert check.done_by == 'user-worker-001' and check.done_at == original
