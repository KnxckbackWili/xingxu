"""项目移交、阶段及计划边界。"""

from datetime import date
import pytest
from app.db import SessionLocal
from app.models import AcceptanceRecord, DailyProgress, Module, Phase, Project, ProjectGovernanceRequest, ScheduleEntry, Task, User


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


def suggest(client, headers, pid, **suggestion):
    return client.post(f'/api/projects/{pid}/schedule/apply-suggestions', headers=headers,
                       json={'suggestions': [suggestion], 'confirm': False})


def test_ai_suggestion_rejects_nonmember_assignee(client, pm_headers, worker_headers):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    worker = client.get('/api/auth/me', headers=worker_headers).json()
    response = suggest(client, pm_headers, pid, task_name='现场检查', assignee=worker['display_name'],
                       recommended_date='2026-09-10')
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        entry = db.get(ScheduleEntry, eid)
        assert entry.work_date == date(2026, 9, 1)
        assert entry.assignee_id != worker['id']


def test_ai_suggestion_rejects_ambiguous_task_without_partial_writes(client, pm_headers):
    pid = project(client, pm_headers)
    _, first, _ = task_entry(pid)
    _, second, _ = task_entry(pid)
    response = suggest(client, pm_headers, pid, task_name='现场检查', recommended_date='2026-09-10')
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert {db.get(ScheduleEntry, eid).work_date for eid in (first, second)} == {date(2026, 9, 1)}


def test_ai_suggestion_rejects_ambiguous_project_member(client, pm_headers):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    with SessionLocal() as db:
        people = db.query(User).filter(User.role == 'worker').all()
        assert len(people) >= 2
        for person in people:
            person.display_name = '同名实施人员'
        db.get(Project, pid).members = [person.id for person in people]
        db.commit()
    response = suggest(client, pm_headers, pid, task_name='现场检查', assignee='同名实施人员')
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.get(ScheduleEntry, eid).assignee_id == db.get(Project, pid).manager


@pytest.mark.parametrize('protection', ['confirmed', 'reported', 'done', 'skipped'])
def test_ai_suggestion_preserves_published_or_historical_work(client, pm_headers, protection):
    pid = project(client, pm_headers)
    tid, eid, _ = task_entry(pid, confirmed=protection == 'confirmed',
                             status=protection if protection in ('done', 'skipped') else 'planned')
    if protection == 'reported':
        with SessionLocal() as db:
            db.add(DailyProgress(project_id=pid, task_id=tid, schedule_entry_id=eid,
                                 user_id=db.get(Project, pid).manager, work_date=date(2026, 9, 1),
                                 completed_quantity=1, client_uuid='round5-existing-report'))
            db.commit()
    response = suggest(client, pm_headers, pid, task_name='现场检查', recommended_date='2026-09-10')
    assert response.status_code == 200, response.text
    assert not response.json()['applied']
    with SessionLocal() as db:
        assert db.get(ScheduleEntry, eid).work_date == date(2026, 9, 1)


@pytest.mark.parametrize('path,payload', [
    ('generate', None), ('confirm', None),
    ('reschedule', {'start_date': '2026-09-10'}),
    ('apply-suggestions', {'suggestions': [{'task_name': '现场检查', 'recommended_date': '2026-09-10'}]}),
])
def test_completed_project_cannot_create_or_publish_schedules(client, pm_headers, path, payload):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    with SessionLocal() as db:
        db.get(Project, pid).status = 'completed'; db.commit()
    response = client.post(f'/api/projects/{pid}/schedule/{path}', headers=pm_headers, json=payload)
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.get(ScheduleEntry, eid).work_date == date(2026, 9, 1)
        assert not db.get(ScheduleEntry, eid).is_confirmed
        assert db.get(Project, pid).schedule_version == 0


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


def test_transfer_blocks_unfinished_published_work_until_reassigned(client, pm_headers, admin_headers):
    from tests.test_governance_lifecycle_backup import _create_user
    target = _create_user(client, admin_headers, 'round5-receiver')
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid, confirmed=True)
    request = client.post(f'/api/projects/{pid}/governance-requests', headers=pm_headers, json={
        'request_type': 'transfer', 'target_manager_id': target, 'reason': '项目负责人岗位移交',
    })
    assert request.status_code == 200, request.text
    rid = request.json()['id']
    path = f'/api/projects/governance/requests/{rid}/review'
    response = client.post(path, headers=admin_headers, json={'decision': 'approved'})
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.get(ProjectGovernanceRequest, rid).status == 'pending'
        assert db.get(Project, pid).manager != target
        assert db.get(ScheduleEntry, eid).assignee_id == db.get(Project, pid).manager
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json={'members': [target]}).status_code == 200
    assert client.put(f'/api/schedule/{eid}', headers=pm_headers, json={'assignee_id': target}).status_code == 200
    response = client.post(path, headers=admin_headers, json={'decision': 'approved'})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(Project, pid).manager == target
        assert db.get(ScheduleEntry, eid).assignee_id == target


def test_preparation_legacy_required_date_changes_invalidate_review_token(client, pm_headers):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    item = client.post(path, headers=pm_headers, json={
        'name': '旧日期字段事项', 'planned_date': '2026-09-30',
    }).json()
    review = client.post(path.replace('/procurements', '/preparations') + '/review', headers=pm_headers).json()
    changed = client.put(path + '/' + item['id'], headers=pm_headers, json={'planned_date': '2026-08-01'})
    assert changed.status_code == 200, changed.text
    response = client.post(path.replace('/procurements', '/preparations') + '/review/confirm', headers=pm_headers, json={
        'conclusion': 'risky', 'notes': '按已查看的风险清单安排现场核对', 'review_token': review['review_token'],
    })
    assert response.status_code == 409, response.text


def test_schedule_explicit_null_clears_assignee(client, pm_headers):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    response = client.put(f'/api/schedule/{eid}', headers=pm_headers, json={'assignee_id': None})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(ScheduleEntry, eid).assignee_id is None


@pytest.mark.parametrize('year', [0, 10000])
def test_schedule_calendar_rejects_unsupported_year(client, pm_headers, year):
    pid = project(client, pm_headers)
    response = client.get('/api/schedule/calendar', headers=pm_headers,
                          params={'project_id': pid, 'year': year, 'month': 9})
    assert response.status_code == 422, response.text


def test_published_schedule_invalidates_stale_entry_edit(client, pm_headers):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    with SessionLocal() as db:
        version = db.get(ScheduleEntry, eid).version
    assert client.post(f'/api/projects/{pid}/schedule/confirm', headers=pm_headers).status_code == 200
    response = client.put(f'/api/schedule/{eid}', headers=pm_headers,
                          json={'is_confirmed': False, 'work_date': '2026-09-10', 'version': version})
    assert response.status_code == 409, response.text


@pytest.mark.parametrize('changes', [
    {'forecast_date': '2026-11-05'}, {'required_date': '2026-10-01'},
])
def test_new_or_tighter_preparation_deadline_requires_reconfirmation(client, pm_headers, changes):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    item = client.post(path, headers=pm_headers, json={
        'name': '带风险准备事项', 'required_date': '2026-11-01', 'risk': 'low',
    }).json()
    confirmed = client.post(path.replace('/procurements', '/preparations') + '/review/confirm', headers=pm_headers,
                            json={'conclusion': 'risky', 'notes': '按当前准备日期和未完成事项安排跟进'})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['summary']['entry_confirmed']
    changed = client.put(path + '/' + item['id'], headers=pm_headers, json=changes)
    assert changed.status_code == 200, changed.text
    summary = client.get(path, headers=pm_headers).json()['summary']
    assert not summary['entry_confirmed']
    assert summary['void']


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


def test_review_keeps_distinct_same_named_risks(client, pm_headers):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    ids = set()
    for _ in range(2):
        result = client.post(path, headers=pm_headers, json={'name': '同名准备风险', 'risk': 'high'})
        assert result.status_code == 200, result.text
        ids.add(result.json()['id'])
    risks = client.post(path.replace('/procurements', '/preparations') + '/review', headers=pm_headers).json()['risks']
    assert {row['id'] for row in risks if row['name'] == '同名准备风险'} == ids


def test_cancelled_schedule_not_counted_in_calendar(client, pm_headers):
    pid = project(client, pm_headers)
    task_entry(pid, status='skipped')
    response = client.get('/api/schedule/calendar', headers=pm_headers,
                          params={'project_id': pid, 'year': 2026, 'month': 9})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize('operation', ['generate', 'reschedule'])
def test_schedule_rechecks_project_status_after_lock(client, pm_headers, operation):
    from fastapi import HTTPException
    from app.services.scheduler import generate_schedule, reschedule_from
    pid = project(client, pm_headers)
    task_entry(pid)
    with SessionLocal() as stale:
        previous = stale.get(Project, pid)
        assert previous.status == 'planning'
        with SessionLocal() as newer:
            newer.get(Project, pid).status = 'completed'
            newer.commit()
        with pytest.raises(HTTPException) as error:
            if operation == 'generate':
                generate_schedule(stale, previous)
            else:
                reschedule_from(stale, previous, date(2026, 9, 10))
        assert error.value.status_code == 400


def test_status_transition_revalidates_after_lock(client, pm_headers, monkeypatch):
    from app.services.record_lock import lock_record
    pid = project(client, pm_headers)
    def concurrent_pause(db, entity, **kwargs):
        with SessionLocal() as other:
            current = other.get(Project, pid)
            current.status = 'suspended'
            current.suspension = {'status_before': 'planning', 'reason': '现场暂缓'}
            other.commit()
        lock_record(db, entity, **kwargs)
    monkeypatch.setattr('app.services.record_lock.lock_record', concurrent_pause)
    response = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'ready'})
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.get(Project, pid).status == 'suspended'


def test_schedule_edit_handles_draft_removed_while_waiting(client, pm_headers, monkeypatch):
    from app.routers.schedules import lock_schedule_project
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    def concurrent_replan(db, current, viewer=None):
        with SessionLocal() as other:
            other.delete(other.get(ScheduleEntry, eid))
            other.commit()
        lock_schedule_project(db, current, viewer)
    monkeypatch.setattr('app.routers.schedules.lock_schedule_project', concurrent_replan)
    response = client.put(f'/api/schedule/{eid}', headers=pm_headers, json={'work_date': '2026-09-10'})
    assert response.status_code == 409, response.text


@pytest.mark.parametrize('operation', ['edit'])
def test_archiving_invalidates_preloaded_project_write(client, pm_headers, admin_headers, monkeypatch, operation):
    from app.models import ArchiveChecklist
    from app.routers.projects import change_status, ProjectStatusChange
    from app.services.optimistic import bump_version
    pid = project(client, pm_headers)
    with SessionLocal() as db:
        current = db.get(Project, pid)
        current.status = 'completed'
        current.retrospective = {'content': '已完成复盘'}
        for item in db.query(ArchiveChecklist).filter_by(project_id=pid):
            item.is_done = True
        db.commit()
    from tests.document_helpers import complete_documents
    complete_documents(client, pm_headers, pid)
    from tests.lifecycle_helpers import sign_current_scope
    sign_current_scope(client, pm_headers, pid)
    entered = []
    def commit_concurrent_archive(entity):
        if isinstance(entity, Project) and entity.id == pid and not entered:
            entered.append(True)
            with SessionLocal() as concurrent:
                fresh = concurrent.get(Project, pid)
                operator = concurrent.get(User, fresh.manager)
                result = change_status(pid, ProjectStatusChange(status='archived'), operator, fresh, concurrent)
                assert result['status'] == 'archived'
    # Editing now serializes on Project before its CAS. A second writer
    # cannot archive after that lock is held: model the real race between
    # the initial visibility read and acquiring the project lock instead.
    from app.services.record_lock import lock_record
    def archive_before_lock(db, entity, **kwargs):
        commit_concurrent_archive(entity)
        return lock_record(db, entity, **kwargs)
    monkeypatch.setattr('app.services.record_lock.lock_record', archive_before_lock)
    response = client.put(f'/api/projects/{pid}', headers=pm_headers, json={'name': '归档后不应生效'})
    assert response.status_code == 400, response.text
    assert entered == [True]
    with SessionLocal() as db:
        saved = db.get(Project, pid)
        assert saved.status == 'archived'
        assert saved.name == '生命周期复核'


def test_unchanged_ai_draft_can_be_published_without_republishing_on_retry(client, pm_headers):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    payload = {'suggestions': [{'task_name': '现场检查', 'recommended_date': '2026-09-01'}], 'confirm': True}
    path = f'/api/projects/{pid}/schedule/apply-suggestions'
    first = client.post(path, headers=pm_headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()['schedule_version'] == 1
    with SessionLocal() as db:
        assert db.get(ScheduleEntry, eid).is_confirmed
    retry = client.post(path, headers=pm_headers, json=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json()['applied'] == []
    assert retry.json()['schedule_version'] == 1
