"""当前项目、采购、附件和状态边界；原日程夹具仅作只读历史来源。"""


from datetime import date
import pytest
from app.db import SessionLocal
from app.models import AcceptanceRecord, Module, Phase, Project, ScheduleEntry, Task, User


def project(client, headers, name='生命周期复核'):
    response = client.post('/api/projects', headers=headers, json={
        'name': name, 'start_date': '2026-09-01', 'end_date': '2026-12-31',
        'new_vehicles': False,
        'status': 'preparing',  # New projects begin at the current manual lifecycle entry.
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


def task_entry(pid, *, name='现场检查', confirmed=False, status='planned', locked=False):
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='现场实施', sort_order=1)
        db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='执行', sort_order=1)
        db.add(module); db.flush()
        task = Task(project_id=pid, module_id=module.id, name=name, target_quantity=2, standard_hours=4)
        db.add(task); db.flush()
        entry = ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2026, 9, 1),
                              assignee_id=db.get(Project, pid).manager, planned_quantity=2,
                              is_confirmed=confirmed, is_locked=locked, status=status)
        db.add(entry); db.commit()
        return task.id, entry.id, phase.id


@pytest.mark.parametrize('field', ['affected_task_id', 'affected_phase_id'])
@pytest.mark.parametrize('method', ['post', 'put'])
def test_preparation_rejects_foreign_execution_reference(client, pm_headers, field, method):
    pid, other = project(client, pm_headers), project(client, pm_headers, '外部项目')
    tid, _, phase_id = task_entry(other)
    path = f'/api/projects/{pid}/procurements'
    data = {'name': '准备核查', field: tid if field == 'affected_task_id' else phase_id}
    if method == 'put':
        created = client.post(path, headers=pm_headers, json={'name': '准备核查'}).json()
        path += '/' + created['id']
    response = getattr(client, method)(path, headers=pm_headers, json=data)
    assert response.status_code == 400, response.text


def test_preparation_can_clear_impact_links(client, pm_headers):
    pid = project(client, pm_headers)
    tid, _, phase_id = task_entry(pid)
    path = f'/api/projects/{pid}/procurements'
    created = client.post(path, headers=pm_headers, json={
        'name': '准备核查', 'affected_task_id': tid, 'affected_phase_id': phase_id,
    })
    assert created.status_code == 200, created.text
    response = client.put(path + '/' + created.json()['id'], headers=pm_headers,
                          json={'affected_task_id': None, 'affected_phase_id': None})
    assert response.status_code == 200, response.text
    assert response.json()['affected_task_id'] is None
    assert response.json()['affected_phase_id'] is None


@pytest.mark.parametrize('kind', ['acceptance', 'documents'])
def test_completion_evidence_cannot_reference_foreign_attachment(client, pm_headers, kind):
    pid, other = project(client, pm_headers), project(client, pm_headers, '附件来源项目')
    attachment = client.post(f'/api/projects/{other}/documents/files', headers=pm_headers,
                             files={'file': ('signed.txt', b'evidence', 'text/plain')})
    assert attachment.status_code == 200, attachment.text
    aid = attachment.json()['file']['id']
    with SessionLocal() as db:
        db.get(Project, pid).status = 'acceptance'; db.commit()
    if kind == 'acceptance':
        response = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers,
                               json={'accepted_by_name': '验收人', 'accepted_at': '2026-09-30', 'attachment_id': aid})
    else:
        from tests.document_helpers import documents
        row = documents(client, pm_headers, pid)['documents'][0]
        response = client.post(f'/api/projects/{pid}/documents/submit', headers=pm_headers, json={'document_ids': [row['id']], 'attachment_id': aid})
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.query(AcceptanceRecord).filter_by(project_id=pid).count() == 0


@pytest.mark.parametrize('field,value', [('risk', 'unknown'), ('owner_party', 'unknown'), ('name', '')])
def test_preparation_updates_preserve_create_field_validation(client, pm_headers, field, value):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    item = client.post(path, headers=pm_headers, json={'name': '合法准备项'}).json()
    response = client.put(path + '/' + item['id'], headers=pm_headers, json={field: value})
    assert response.status_code == 422, response.text


def test_preparation_uses_project_local_date_for_completion_and_overdue(client, pm_headers, monkeypatch):
    local_today = date(2026, 10, 1)
    monkeypatch.setattr('app.time_utils.project_today', lambda tz: local_today)
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    created = client.post(path, headers=pm_headers, json={
        'name': '本地日期', 'required_date': '2026-09-30',
    }).json()
    summary = client.get(path, headers=pm_headers).json()['summary']
    assert summary['overdue'] >= 1
    changed = client.put(path + '/' + created['id'], headers=pm_headers, json={'status': 'passed'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['actual_date'] == local_today.isoformat()


def test_status_transition_revalidates_after_lock(client, pm_headers, monkeypatch):
    from app.services.record_lock import lock_record
    pid = project(client, pm_headers)
    def concurrent_pause(db, entity, **kwargs):
        with SessionLocal() as other:
            current = other.get(Project, pid)
            current.status = 'suspended'
            current.suspension = {'status_before': 'preparing', 'reason': '现场暂缓'}
            other.commit()
        lock_record(db, entity, **kwargs)
    monkeypatch.setattr('app.services.record_lock.lock_record', concurrent_pause)
    response = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'ready'})
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.get(Project, pid).status == 'suspended'


def test_archiving_invalidates_preloaded_project_write(client, pm_headers, monkeypatch):
    """An archive committed between the edit's visibility read and its project
    lock must win: the stale edit is rejected and cannot write the old state back."""
    from app.routers.projects import change_status, ProjectStatusChange
    from app.services.record_lock import lock_record
    from tests.test_lifecycle_write_integrity import completeable_project
    pid, _, _ = completeable_project(client, pm_headers)
    status_path = f'/api/projects/{pid}/status'
    assert client.post(status_path, headers=pm_headers, json={'status': 'completed'}).status_code == 200
    before = client.get(f'/api/projects/{pid}', headers=pm_headers).json()
    entered = []

    def archive_before_lock(db, entity, **kwargs):
        if isinstance(entity, Project) and entity.id == pid and not entered:
            entered.append(True)
            with SessionLocal() as concurrent:
                fresh = concurrent.get(Project, pid)
                operator = concurrent.get(User, fresh.manager)
                result = change_status(pid, ProjectStatusChange(status='archived', retrospective='并发归档复盘'), operator, fresh, concurrent)
                assert result['status'] == 'archived'
            with SessionLocal() as proof:
                assert proof.get(Project, pid).status == 'archived'
        return lock_record(db, entity, **kwargs)

    monkeypatch.setattr('app.services.record_lock.lock_record', archive_before_lock)
    response = client.put(f'/api/projects/{pid}', headers=pm_headers,
                          json={'name': '归档后不应生效', 'version': before['version']})
    assert response.status_code in (400, 409), response.text
    assert entered == [True]
    with SessionLocal() as db:
        saved = db.get(Project, pid)
        assert saved.status == 'archived'
        assert saved.name == before['name']
