"""现场事实等待共享项目锁后复核生命周期和当前参与者资格。"""
from datetime import date
from uuid import uuid4
import pytest
from app.db import SessionLocal
from app.models import FieldOperation, Project, Task, VehicleProgress
from app.time_utils import project_today, utcnow
from tests.test_field_week_t33 import prepared, operation as vehicle_operation, save


def _context(client, pm_headers):
    pid, unit, people = prepared(client, pm_headers)
    response = client.post(f'/api/projects/{pid}/work-phases', headers=pm_headers, json={'name': '实施工作'})
    assert response.status_code == 200, response.text
    response = client.post(f'/api/projects/{pid}/work-items', headers=pm_headers,
        json={'phase_id': response.json()['id'], 'name': '状态竞争工作', 'kind': 'other'})
    assert response.status_code == 200, response.text
    return pid, unit, response.json()['id'], people


def _request(client, pm_headers, worker_headers, pid, unit, tid, action):
    today = project_today('Asia/Shanghai').isoformat()
    if action == 'vehicle':
        return 'POST', '/api/worker/operations', vehicle_operation(pid, unit), worker_headers
    if action == 'retract':
        response = save(client, worker_headers, vehicle_operation(pid, unit))
        assert response.status_code == 200, response.text
        record = response.json()
        return 'DELETE', '/api/worker/records/' + record['id'], {
            'version': record['version'], 'completion_date': today,
            'reason': '本人核对后撤回', 'client_uuid': str(uuid4())}, worker_headers
    body = {'project_id': pid, 'kind': 'work', 'target_id': tid, 'is_done': True,
        'completion_date': today, 'reason': '现场完成该工作', 'version': 0, 'client_uuid': str(uuid4())}
    if action == 'reopen':
        response = save(client, pm_headers, body)
        assert response.status_code == 200, response.text
        body.update(is_done=False, version=response.json()['version'], reason='现场复核需要重新处理', client_uuid=str(uuid4()))
    return 'POST', '/api/worker/operations', body, pm_headers


def _snapshot(pid, unit, tid):
    with SessionLocal() as db:
        task = db.get(Task, tid)
        progress = db.query(VehicleProgress).filter_by(project_id=pid, vehicle_unit_id=unit).all()
        return (task.manually_completed, task.version,
            sorted((r.step_key, r.is_done, r.done_on, r.version) for r in progress),
            db.query(FieldOperation).filter_by(project_id=pid).count())


def _interleave(monkeypatch, pid, mutation):
    from app.services import field_operations
    original = field_operations.lock_writable_project
    calls = []
    def commit_before_lock(db, project, user):
        assert project.id == pid
        with SessionLocal() as other:
            mutation(other, other.get(Project, pid))
            other.commit()
        calls.append(project.id)
        return original(db, project, user)
    monkeypatch.setattr(field_operations, 'lock_writable_project', commit_before_lock)
    return calls


@pytest.mark.parametrize('action', ['vehicle', 'retract', 'complete', 'reopen'])
@pytest.mark.parametrize('state', ['completed', 'archived', 'deleted'])
def test_field_write_rechecks_project_state_after_lock(client, pm_headers, worker_headers, monkeypatch, action, state):
    pid, unit, tid, _ = _context(client, pm_headers)
    method, url, body, headers = _request(client, pm_headers, worker_headers, pid, unit, tid, action)
    before = _snapshot(pid, unit, tid)
    def transition(db, project):
        if state == 'deleted':
            project.deleted_at = utcnow()
        else:
            project.status = state
    calls = _interleave(monkeypatch, pid, transition)
    response = client.request(method, url, headers=headers, json=body)
    assert calls == [pid], 'The competing commit must happen between context read and the real project lock'
    expected = 404 if state == 'deleted' else 409 if state == 'completed' and action == 'retract' else 400
    assert response.status_code == expected, response.text
    assert _snapshot(pid, unit, tid) == before
    with SessionLocal() as db:
        current = db.get(Project, pid)
        assert current.deleted_at is not None if state == 'deleted' else current.status == state

