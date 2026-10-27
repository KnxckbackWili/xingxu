"""资料版本、离线回执及现场写入边界。"""

from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Task, DailyProgress, ScheduleEntry
from app.time_utils import project_today
from tests.test_execution_workflow_audit import _execution


def test_offline_report_uses_envelope_uuid(client, worker_headers):
    _, tid, _ = _execution(client)
    op = {'type': 'report', 'client_uuid': 'envelope-report-001', 'payload': {
        'task_id': tid, 'work_date': date.today().isoformat(), 'completed_quantity': 1}}
    first = client.post('/api/worker/sync', headers=worker_headers, json={'ops': [op]})
    assert first.json()['accepted'] == [op['client_uuid']], first.text
    second = {**op, 'client_uuid': 'envelope-report-002', 'payload': {**op['payload'], 'client_uuid': op['client_uuid']}}
    assert client.post('/api/worker/sync', headers=worker_headers, json={'ops': [second]}).json()['accepted'] == [second['client_uuid']]
    assert client.post('/api/worker/sync', headers=worker_headers, json={'ops': [op, second]}).json()['rejected'] == []
    with SessionLocal() as db:
        reports = db.query(DailyProgress).filter_by(task_id=tid).all()
        assert len(reports) == 2 and sum(r.completed_quantity for r in reports) == 2


def test_legacy_offline_document_honors_frozen_source_version(client, worker_headers, pm_headers):
    from tests.document_helpers import legacy_document, upload_documents
    from app.models import ProjectDocument, OfflineOpReceipt
    pid, tid, _ = _execution(client)
    with SessionLocal() as db:
        db.get(Task, tid).version = 2; db.commit()
    did = legacy_document(client, pm_headers, pid, tid, name='验收单')
    asset = upload_documents(client, worker_headers, pid)['file']
    operation = {'type': 'deliverable', 'client_uuid': 'stale-delivery-001', 'payload': {
        'project_id': pid, 'task_id': tid, 'version': 1, 'deliverables': [{'name': '验收单', 'done': True, 'attachment_id': asset['id']}]}}
    from copy import deepcopy
    before = deepcopy(operation)
    result = client.post('/api/worker/sync', headers=worker_headers, json={'ops': [operation]})
    assert result.json()['rejected'] == ['stale-delivery-001'] and '版本' in result.json()['rejected_detail']['stale-delivery-001']
    assert operation == before
    with SessionLocal() as db:
        assert db.get(ProjectDocument, did).status == 'pending'
        assert db.query(OfflineOpReceipt).filter_by(client_uuid='stale-delivery-001').count() == 0


def test_document_submission_preserves_requirement_snapshots_and_other_rows(client, worker_headers, pm_headers):
    from tests.document_helpers import requirement, documents, upload_documents
    pid, _, _ = _execution(client)
    first = requirement(client, pm_headers, pid, name='签字单', code='6.99')
    second = requirement(client, pm_headers, pid, name='现场照片', code='6.98', required=False)
    uploaded = upload_documents(client, worker_headers, pid, [first['id']], required='false')['documents'][0]
    assert uploaded['required'] is True and uploaded['name'] == '签字单'
    after = {row['id']: row for row in documents(client, pm_headers, pid)['documents']}
    assert after[second['id']] == second
    assert len(uploaded['versions']) == 1


def test_worker_submits_next_document_without_mutating_prior_review(client, worker_headers, pm_headers):
    from tests.document_helpers import requirement, documents, upload_documents
    pid, _, _ = _execution(client)
    first = requirement(client, pm_headers, pid, name='第一单', code='6.99')
    second = requirement(client, pm_headers, pid, name='第二单', code='6.98')
    prior = upload_documents(client, worker_headers, pid, [first['id']])['documents'][0]
    version = prior['versions'][0]
    review = client.post(f'/api/projects/{pid}/documents/{first["id"]}/versions/{version["id"]}/review', headers=pm_headers, json={'decision': 'approved'})
    assert review.status_code == 200, review.text
    upload_documents(client, worker_headers, pid, [second['id']])
    after = {row['id']: row for row in documents(client, pm_headers, pid)['documents']}
    assert after[first['id']]['versions'][0] == review.json()
    assert after[second['id']]['status'] == 'submitted'


def test_replacement_file_creates_unreviewed_version_and_preserves_approved_original(client, worker_headers, pm_headers):
    from tests.document_helpers import requirement, documents, upload_documents
    pid, _, _ = _execution(client)
    row = requirement(client, pm_headers, pid)
    first = upload_documents(client, worker_headers, pid, [row['id']], content=b'first')['documents'][0]
    version = first['versions'][0]
    reviewed = client.post(f'/api/projects/{pid}/documents/{row["id"]}/versions/{version["id"]}/review', headers=pm_headers, json={'decision': 'approved'})
    assert reviewed.status_code == 200, reviewed.text
    next_file = upload_documents(client, worker_headers, pid, content=b'next')['file']
    result = client.post(f'/api/projects/{pid}/documents/submit', headers=worker_headers, json={'document_ids': [row['id']], 'attachment_id': next_file['id']})
    assert result.status_code == 200, result.text
    current = next(value for value in documents(client, pm_headers, pid)['documents'] if value['id'] == row['id'])
    assert len(current['versions']) == 2
    kept = next(value for value in current['versions'] if value['id'] == version['id'])
    assert kept == reviewed.json()
    assert not current['latest_version']['review_metadata']
    assert client.get('/api' + kept['download_url'], headers=pm_headers).content == b'first'


@pytest.mark.parametrize('target', ['missing', 'another-project'])
def test_document_attachment_must_belong_to_project(client, worker_headers, pm_headers, target):
    from tests.document_helpers import requirement, upload_documents
    pid, _, _ = _execution(client)
    row = requirement(client, pm_headers, pid)
    aid = 'missing'
    if target == 'another-project':
        other, _, _ = _execution(client)
        aid = upload_documents(client, worker_headers, other)['file']['id']
    result = client.post(f'/api/projects/{pid}/documents/submit', headers=worker_headers, json={'document_ids': [row['id']], 'attachment_id': aid})
    assert result.status_code == 400, result.text


def test_duplicate_document_selection_rejected_without_versions(client, worker_headers, pm_headers):
    from tests.document_helpers import requirement, documents, upload_documents
    pid, _, _ = _execution(client)
    row = requirement(client, pm_headers, pid)
    asset = upload_documents(client, worker_headers, pid)['file']
    response = client.post(f'/api/projects/{pid}/documents/submit', headers=worker_headers, json={'document_ids': [row['id'], row['id']], 'attachment_id': asset['id']})
    assert response.status_code == 422, response.text
    kept = next(value for value in documents(client, pm_headers, pid)['documents'] if value['id'] == row['id'])
    assert kept['status'] == 'pending' and not kept['versions']


def test_today_and_check_update_expose_versions(client, worker_headers):
    pid, tid, cid = _execution(client)
    with SessionLocal() as db:
        db.get(Task, tid).version = 7
        db.add(ScheduleEntry(project_id=pid, task_id=tid, work_date=project_today('Asia/Shanghai'),
            planned_quantity=10, is_confirmed=True, assignee_id='user-worker-001')); db.commit()
    row = client.get('/api/worker/today', headers=worker_headers).json()['items'][0]
    assert row['task_version'] == 7 and row['check_items'][0]['version'] == 0
    response = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=worker_headers, json={'is_done': True, 'version': 0})
    assert response.status_code == 200 and response.json()['version'] == 1


def test_reopening_vehicle_issue_restores_attention_without_status_field(client, pm_headers):
    pid, _, _ = _execution(client)
    unit = client.post(f'/api/projects/{pid}/vehicle-units', headers=pm_headers, json={'asset_code': 'AGV-R5'}).json()['id']
    base = f'/api/projects/{pid}/vehicle-units/{unit}'
    event = client.post(base + '/events', headers=pm_headers, json={
        'event_type': 'fault', 'event_date': date.today().isoformat(), 'title': '故障', 'status_after': 'fault'}).json()['id']
    assert client.put(base + '/events/' + event, headers=pm_headers, json={'is_closed': True, 'status_after': 'normal'}).status_code == 200
    assert client.get(base, headers=pm_headers).json()['current_status'] == 'normal'
    response = client.put(base + '/events/' + event, headers=pm_headers, json={'is_closed': False})
    assert response.status_code == 200
    assert client.get(base, headers=pm_headers).json()['current_status'] == 'attention'


@pytest.mark.parametrize('action,initial,quantity', [('report', .994, .008)])
def test_report_bounds_use_raw_totals_not_display_rounding(client, pm_headers, action, initial, quantity):
    pid, tid, _ = _execution(client)
    with SessionLocal() as db:
        db.get(Task, tid).target_quantity = 1
        db.add(DailyProgress(project_id=pid, task_id=tid, user_id='user-pm-001', work_date=date.today(),
            completed_quantity=initial, client_uuid='raw-bound-initial')); db.commit()
    payload = {'task_id': tid, 'client_uuid': 'raw-bound-add'}
    payload.update(work_date=date.today().isoformat(), completed_quantity=quantity); url = '/api/worker/reports'
    response = client.post(url, headers=pm_headers, json=payload)
    assert response.status_code == 400, response.text


def test_concurrent_different_report_ids_cannot_overfill_task(client, pm_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.models import User
    from app.routers.worker import submit_report, ProgressSubmit
    pid, tid, _ = _execution(client)
    with SessionLocal() as db:
        db.get(Task, tid).target_quantity = 1; db.commit()
    gate = Barrier(2)
    def send(n):
        with SessionLocal() as db:
            user = db.get(User, 'user-pm-001')
            gate.wait(timeout=5)
            try:
                result = submit_report(ProgressSubmit(task_id=tid, work_date=date.today(),
                    completed_quantity=1, client_uuid=f'concurrent-report-{n}'), user, db)
                return 200 if result['accepted'] else 409
            except HTTPException as exc:
                db.rollback(); return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(send, range(2)))
    assert outcomes == [200, 400], outcomes
    with SessionLocal() as db:
        assert sum(r.completed_quantity for r in db.query(DailyProgress).filter_by(task_id=tid)) == 1


def test_offline_versioned_operation_retry_acknowledges_saved_receipt(client, worker_headers):
    pid, _, cid = _execution(client)
    op = {'type': 'checkitem', 'client_uuid': 'saved-version-001', 'payload': {
        'project_id': pid, 'check_item_id': cid, 'body': {'is_done': True, 'version': 0}}}
    for _ in range(2):
        response = client.post('/api/worker/sync', headers=worker_headers, json={'ops': [op]})
        assert response.json()['accepted'] == [op['client_uuid']], response.text


@pytest.mark.parametrize('action', ['report'])
def test_saved_report_retry_acknowledged_after_project_completion(client, pm_headers, action):
    from app.models import Project
    pid, tid, _ = _execution(client)
    url = '/api/worker/reports'
    payload = {'task_id': tid, 'work_date': date.today().isoformat(), 'completed_quantity': 1, 'client_uuid': 'complete-retry-report'}
    assert client.post(url, headers=pm_headers, json=payload).json()['accepted'] is True
    with SessionLocal() as db:
        db.get(Project, pid).status = 'completed'; db.commit()
    response = client.post(url, headers=pm_headers, json=payload)
    assert response.status_code == 200 and response.json()['accepted'] is False, response.text
    fresh = client.post(url, headers=pm_headers, json={**payload, 'client_uuid': 'new-after-completion'})
    assert fresh.status_code == 400


def test_completed_project_cannot_retract_execution(client, worker_headers):
    from app.models import Project
    pid, tid, _ = _execution(client)
    response = client.post('/api/worker/reports', headers=worker_headers, json={
        'task_id': tid, 'work_date': project_today('Asia/Shanghai').isoformat(), 'completed_quantity': 1, 'client_uuid': 'completed-record'})
    rid = response.json()['id']
    with SessionLocal() as db:
        db.get(Project, pid).status = 'completed'; db.commit()
    records = client.get('/api/worker/records', headers=worker_headers).json()
    assert next(r for r in records if r['id'] == rid)['can_retract'] is False
    result = client.delete('/api/worker/reports/' + rid, headers=worker_headers)
    assert result.status_code == 400, result.text


@pytest.mark.parametrize('state', ['pass', 'fail'])
def test_check_switching_from_na_restores_applicability(client, worker_headers, state):
    pid, _, cid = _execution(client)
    url = f'/api/projects/{pid}/check-items/{cid}'
    assert client.put(url, headers=worker_headers, json={'is_applicable': False, 'not_applicable_reason': '原现场不适用'}).status_code == 200
    payload = {'is_done': True} if state == 'pass' else {'failed': True, 'failed_reason': '重新检查失败'}
    result = client.put(url, headers=worker_headers, json=payload)
    assert result.status_code == 200 and result.json()['is_applicable'] is True, result.text
    assert result.json()['not_applicable_reason'] == ''
    assert result.json()['is_done'] is (state == 'pass')
    assert result.json()['failed'] is (state == 'fail')


@pytest.mark.parametrize('left,right,same', [('report', 'report', False), ('report', 'report', True)])
def test_progress_writes_share_task_lock(client, pm_headers, left, right, same):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.models import User
    from app.routers.worker import submit_report, ProgressSubmit
    _, tid, _ = _execution(client)
    with SessionLocal() as db:
        db.get(Task, tid).target_quantity = 1; db.commit()
    gate = Barrier(2)
    def send(n):
        with SessionLocal() as db:
            user = db.get(User, 'user-pm-001'); gate.wait(timeout=5)
            key = 'shared-progress-key' if same else f'shared-progress-{n}'
            try:
                result = submit_report(ProgressSubmit(task_id=tid, work_date=date.today(), completed_quantity=1, client_uuid=key), user, db)
                return 'accepted' if result['accepted'] else 'duplicate'
            except HTTPException as exc:
                db.rollback(); return str(exc.status_code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(send, range(2)))
    assert outcomes == sorted(['accepted', 'duplicate' if same else '400']), outcomes
    with SessionLocal() as db:
        assert sum(r.completed_quantity for r in db.query(DailyProgress).filter_by(task_id=tid)) == 1


def test_lock_timeout_returns_retriable_conflict(client, pm_headers, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy.exc import OperationalError
    from app.routers.worker import _lock_task_progress
    _, tid, _ = _execution(client)
    with SessionLocal() as db:
        task = db.get(Task, tid)
        from sqlalchemy.sql.dml import Update
        original_execute = db.execute
        def locked(statement, *args, **kwargs):
            if isinstance(statement, Update):
                raise OperationalError('UPDATE tasks', {}, Exception('database is locked'))
            return original_execute(statement, *args, **kwargs)
        monkeypatch.setattr(db, 'execute', locked)
        with pytest.raises(HTTPException) as error:
            _lock_task_progress(db, task)
        assert error.value.status_code == 409


@pytest.mark.parametrize('operation', ['check', 'delivery', 'issue_create', 'issue_update', 'vehicle_event', 'inventory_create', 'inventory_movement', 'attachment_upload', 'attachment_delete'])
@pytest.mark.parametrize('transition', ['archived', 'removed'])
def test_field_mutations_recheck_project_after_waiting_for_lock(client, pm_headers, monkeypatch, operation, transition):
    from app.models import Project, ProjectMember
    from app.services import record_lock
    pid, tid, cid = _execution(client)
    extra_id = None
    if operation == 'delivery':
        from tests.document_helpers import requirement
        extra_id = requirement(client, pm_headers, pid)['id']
    if operation == 'issue_update':
        extra_id = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '现场问题'}).json()['id']
    elif operation == 'vehicle_event':
        extra_id = client.post(f'/api/projects/{pid}/vehicle-units', headers=pm_headers, json={'asset_code': 'LOCK-AGV'}).json()['id']
    elif operation == 'inventory_movement':
        extra_id = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers, json={'name': '现场物品', 'quantity': 1}).json()['id']
    elif operation == 'attachment_delete':
        extra_id = client.post(f'/api/projects/{pid}/documents/files', headers=pm_headers,
            files={'file': ('evidence.txt', b'keep', 'text/plain')}).json()['file']['id']
    original = record_lock.lock_record
    interleaved = []
    def transition_before_lock(db, entity, **kwargs):
        if isinstance(entity, Project) and entity.id == pid and not interleaved:
            with SessionLocal() as other:
                project = other.get(Project, pid)
                if transition == 'archived':
                    project.status = 'archived'
                else:
                    project.manager = 'user-admin-001'
                    other.query(ProjectMember).filter_by(project_id=pid, user_id='user-pm-001').delete()
                other.commit()
            interleaved.append(True)
        return original(db, entity, **kwargs)
    monkeypatch.setattr(record_lock, 'lock_record', transition_before_lock)
    if operation == 'check':
        response = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=pm_headers, json={'is_done': True})
    elif operation == 'delivery':
        response = client.put(f'/api/projects/{pid}/documents/{extra_id}', headers=pm_headers, json={'status': 'waived', 'reason': '并发变更后不应保存'})
    elif operation == 'issue_create':
        response = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '迟到的问题'})
    elif operation == 'issue_update':
        response = client.put('/api/issues/' + extra_id, headers=pm_headers, json={'status': 'resolved'})
    elif operation == 'vehicle_event':
        response = client.post(f'/api/projects/{pid}/vehicle-units/{extra_id}/events', headers=pm_headers,
            json={'event_type': 'fault', 'event_date': date.today().isoformat(), 'title': '迟到的记录'})
    elif operation == 'inventory_create':
        response = client.post(f'/api/projects/{pid}/inventory', headers=pm_headers, json={'name': '迟到的物品'})
    elif operation == 'inventory_movement':
        response = client.post(f'/api/projects/{pid}/inventory/{extra_id}/movements', headers=pm_headers, json={'movement_type': 'consume', 'quantity': 1})
    elif operation == 'attachment_upload':
        response = client.post(f'/api/projects/{pid}/documents/files', headers=pm_headers,
            files={'file': ('late.txt', b'late', 'text/plain')})
    else:
        response = client.delete('/api/files/' + extra_id, headers=pm_headers)
    assert interleaved == [True]
    assert response.status_code == (400 if transition == 'archived' else 404), response.text


def test_check_explicit_not_done_does_not_erase_failure(client, worker_headers):
    pid, _, cid = _execution(client)
    result = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=worker_headers, json={
        'is_applicable': True, 'is_done': False, 'failed': True, 'failed_reason': '本次实测失败'})
    assert result.status_code == 200, result.text
    assert result.json()['failed'] is True and result.json()['is_done'] is False


@pytest.mark.parametrize('fields', [{'failed': True, 'is_done': True}, {'is_applicable': False, 'is_done': True}, {'is_applicable': False, 'failed': True}])
def test_check_conflicting_states_are_rejected(client, worker_headers, fields):
    pid, _, cid = _execution(client)
    response = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=worker_headers, json={
        **fields, 'failed_reason': '状态矛盾', 'not_applicable_reason': '状态矛盾'})
    assert response.status_code == 400, response.text
