"""Quantity reporting, quality verification and issue handling stay distinct."""
from tests.lifecycle_helpers import versioned
from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Project, Phase, Module, Task, CheckItem, DailyProgress
from app.services.progress import project_completion_blockers, task_progress
from tests.test_completion_issue_review import project

@pytest.mark.parametrize('required,safety,manual,done,failed,blocked', [
    (True, False, False, False, False, True), (False, False, False, False, False, False),
    (False, True, False, False, False, True), (True, False, True, False, False, False),
    (True, True, True, False, False, True), (True, True, True, True, True, True),
    (True, True, True, True, False, False),
])
def test_quantity_quality_and_existing_manual_override(client, pm_headers, required, safety, manual, done, failed, blocked):
    pid = project(client, pm_headers)
    uid = client.get('/api/auth/me', headers=pm_headers).json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).status = 'acceptance'; db.commit()
    from tests.lifecycle_helpers import complete_vehicle_progress
    complete_vehicle_progress(client, pm_headers, pid)
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='现场实施'); db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='Module'); db.add(module); db.flush()
        task = Task(project_id=pid, module_id=module.id, name='质量待确认', quantity_type='fixed', unit='项', target_quantity=1, manually_completed=manual)
        db.add(task); db.flush(); tid = task.id
        db.add(CheckItem(project_id=pid, task_id=tid, name='检查', is_required=required, is_safety_critical=safety, is_done=done, failed=failed))
        db.add(DailyProgress(project_id=pid, task_id=tid, user_id=uid, work_date=date.today(), completed_quantity=1, client_uuid='quality-workflow'))
        db.commit()
        assert bool(project_completion_blockers(db, pid)) is blocked
        assert (task_progress(db, tid) < 100) is blocked
        assert db.query(DailyProgress).filter_by(task_id=tid).one().completed_quantity == 1
    handover = client.get(f'/api/projects/{pid}/handover-summary', headers=pm_headers).json()
    assert bool(handover['counts']['tasks']) is blocked
    if safety and blocked and not manual:
        with SessionLocal() as db: version = db.get(Task, tid).version or 0
        result = client.put(f'/api/projects/{pid}/work-items/{tid}/completion', headers=pm_headers,
                            json={'version': version, 'is_completed': True, 'reason': '尝试覆盖安全检查'})
        assert result.status_code == 400 and '必需检查尚未满足' in result.text

def test_completed_issue_reopen_keeps_state_and_notifies_manager(client, pm_headers, worker_headers):
    from app.models import Notification, Issue
    pid = project(client, pm_headers)
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [uid]}))
    issue = client.post(f'/api/projects/{pid}/issues', headers=worker_headers, json={'title': '复发'}).json()
    client.put(f"/api/issues/{issue['id']}", headers=pm_headers, json=versioned(issue['id'], {'status': 'resolved'}, 'Issue'))
    with SessionLocal() as db:
        db.get(Project, pid).status = 'completed'; old_version = db.get(Issue, issue['id']).version; db.commit()
    result = client.post(f"/api/issues/{issue['id']}/reopen", headers=worker_headers)
    assert result.status_code == 200
    with SessionLocal() as db:
        assert db.get(Project, pid).status == 'completed'
        assert db.get(Issue, issue['id']).version == old_version + 1
        assert any('恢复到验收中' in (n.content or '') for n in db.query(Notification).filter_by(project_id=pid).all())
