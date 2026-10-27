"""Stage-five evidence replaces legacy preparations and gates every field write."""
from tests.lifecycle_helpers import versioned
from datetime import timedelta
from uuid import uuid4
import pytest
from app.db import SessionLocal
from app.models import Project, ProjectDocument, ProjectDocumentDefinition, ProjectPreparationItem, ProjectReadinessReview, Attachment, Task, CheckItem, DailyProgress, User
from app.time_utils import utcnow
from tests.test_project_documents import create, view, upload
from tests.test_manual_lifecycle_t28 import state
from tests.test_vehicle_progress import setup_fleet, write
from tests.test_vehicle_checks import work


def scope(client, headers, *, status='ready'):
    pid = create(client, headers)['id']
    with SessionLocal() as db:
        db.query(ProjectDocument).filter_by(project_id=pid, stage_key='5').delete(synchronize_session=False)
        db.query(ProjectDocumentDefinition).filter_by(project_id=pid, stage_key='5').delete(synchronize_session=False)
        db.get(Project, pid).status = status
        db.commit()
    return pid, requirement(client, headers, pid)


def requirement(client, headers, pid, name='发车确认资料'):
    response = client.post(f'/api/projects/{pid}/documents/requirements', headers=headers, json={
        'stage_key': '5', 'code': '5.' + uuid4().hex[:8], 'name': name, 'required': True, 'scope': 'project', 'timing_type': 'on_demand'})
    assert response.status_code == 200, response.text
    return next(row for row in view(client, headers, pid)['documents'] if row['definition_id'] == response.json()['id'])


def preview(client, headers, pid):
    response = client.post(f'/api/projects/{pid}/documents/dispatch-review', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, headers, pid, *, conclusion='risky', notes='次日补齐，现场安排受控', token=None):
    token = token or preview(client, headers, pid)['review_token']
    return client.post(f'/api/projects/{pid}/documents/dispatch-review/confirm', headers=headers, json={'conclusion': conclusion, 'notes': notes, 'review_token': token})


def test_required_documents_real_bytes_and_waiver_replace_procurement_conditions(client, pm_headers):
    pid, doc = scope(client, pm_headers)
    with SessionLocal() as db:
        db.add(ProjectPreparationItem(project_id=pid, name='旧采购缺项', category='procurement', is_required=True, blocks_entry=True, status='failed'))
        db.commit()
    before = preview(client, pm_headers, pid)
    assert len(before['entry_unmet']) == 1 and before['entry_unmet'][0]['id'] == doc['id']
    blocked = state(client, pm_headers, pid, 'executing')
    assert blocked.status_code == 400 and blocked.json()['detail']['blockers'][0]['url'].endswith('/documents?review=1')
    uploaded = upload(client, pm_headers, pid, [doc['id']]); assert uploaded.status_code == 200
    assert not preview(client, pm_headers, pid)['entry_unmet']
    assert state(client, pm_headers, pid, 'executing').status_code == 200
    assert state(client, pm_headers, pid, 'ready').status_code == 200
    with SessionLocal() as db:
        asset = db.get(Attachment, uploaded.json()['file']['id'])
        from app.services.project_documents import file_path
        path = file_path(asset); path.write_bytes(b'x' * asset.file_size)
    assert state(client, pm_headers, pid, 'executing').status_code == 400
    current = next(row for row in view(client, pm_headers, pid)['documents'] if row['id'] == doc['id'])
    assert client.put(f'/api/projects/{pid}/documents/{doc["id"]}', headers=pm_headers, json={'status': 'waived', 'reason': '客户明确无需此资料', 'version': current['version']}).status_code == 200
    assert state(client, pm_headers, pid, 'executing').status_code == 200


def test_risk_requires_reason_and_fresh_preview_and_worsening_invalidates_it(client, pm_headers):
    pid, doc = scope(client, pm_headers)
    token = preview(client, pm_headers, pid)['review_token']
    assert confirm(client, pm_headers, pid, notes=' ', token=token).status_code == 400
    assert confirm(client, pm_headers, pid, conclusion='ready', token=token).status_code == 400
    with SessionLocal() as db:
        row = db.get(ProjectDocument, doc['id']); row.name = '范围已变化'; row.version += 1; db.commit()
    assert confirm(client, pm_headers, pid, token=token).status_code == 409
    assert confirm(client, pm_headers, pid).status_code == 200
    with SessionLocal() as db:
        db.add(ProjectPreparationItem(project_id=pid, name='新采购缺项', category='procurement', is_required=True, blocks_entry=True, status='failed')); db.commit()
    assert state(client, pm_headers, pid, 'executing').status_code == 200
    assert state(client, pm_headers, pid, 'ready').status_code == 200
    requirement(client, pm_headers, pid, '新增必须核对的发车资料')
    assert state(client, pm_headers, pid, 'executing').status_code == 400
    with SessionLocal() as db:
        from app.services.dispatch_review import summary
        assert summary(db, db.get(Project, pid))['void']
    assert confirm(client, pm_headers, pid).status_code == 200
    assert state(client, pm_headers, pid, 'executing').status_code == 200


def test_new_overdue_condition_needs_reapproval_and_legacy_review_grants_no_current_authority(client, pm_headers, monkeypatch):
    pid, doc = scope(client, pm_headers)
    with SessionLocal() as db:
        original = [{'id': 'old-preparation', 'name': '旧准备项', 'status': 'failed'}]
        p = db.get(Project, pid)
        db.add(ProjectReadinessReview(project_id=pid, reviewer_id=p.manager, reviewed_at=utcnow(), conclusion='risky', notes='原准备风险', snapshot=original))
        p.readiness_state='risky'; p.prep_confirmed_at=utcnow(); db.commit()
    assert state(client, pm_headers, pid, 'executing').status_code == 400
    history = client.get(f'/api/projects/{pid}/documents/dispatch-review/history', headers=pm_headers).json()
    assert history[0]['legacy'] is True
    with SessionLocal() as db:
        for row in (db.get(ProjectDocument, doc['id']), db.get(ProjectDocumentDefinition, doc['definition_id'])):
            row.timing_type='before_event'; row.timing_event='ship'; row.timing_offset_hours=1
        db.commit()
    from app.time_utils import project_today
    response=client.put(f'/api/projects/{pid}/events/ship', headers=pm_headers, json=versioned(pid, {'planned_date': (project_today('Asia/Shanghai')+timedelta(days=10)).isoformat()}))
    assert response.status_code == 200, response.text
    assert preview(client, pm_headers, pid)['entry_unmet'][0]['due_at'] is not None
    assert confirm(client, pm_headers, pid).status_code == 200
    with SessionLocal() as db:
        assert db.query(ProjectReadinessReview).filter_by(notes='原准备风险').one().snapshot == original
    future=utcnow()+timedelta(days=20)
    monkeypatch.setattr('app.services.dispatch_review.utcnow', lambda: future)
    assert state(client, pm_headers, pid, 'executing').status_code == 400


@pytest.mark.parametrize('status', ['preparing', 'ready'])
def test_before_execution_all_checks_and_manual_and_quantity_and_offline_ops_are_rejected(client, pm_headers, status):
    pid, units = setup_fleet(client, pm_headers, 1, status=status)
    tid = work(pid, units, safety=False, legacy=True)
    with SessionLocal() as db:
        check = db.query(CheckItem).filter_by(task_id=tid).one(); cid = check.id
        assert check.vehicle_unit_id is None
        db.get(Task, tid).quantity_type='fixed'; db.commit()
    assert write(client, pm_headers, pid, units).status_code == 400
    assert client.put(f'/api/projects/{pid}/check-items/{cid}', headers=pm_headers, json={'is_done': True, 'version': 0}).status_code == 400
    with SessionLocal() as db: version = db.get(Task, tid).version or 0
    early = client.put(f'/api/projects/{pid}/work-items/{tid}/completion', headers=pm_headers,
                       json={'version': version, 'is_completed': True, 'reason': '不能提前填报'})
    assert early.status_code == 400 and '现场实施前' in early.json()['detail']
    body = {'task_id': tid, 'work_date': '2026-01-01', 'completed_quantity': 1, 'client_uuid': str(uuid4())}
    assert client.post('/api/worker/reports', headers=pm_headers, json=body).status_code == 410  # 按日报量已退役
    response = client.post('/api/worker/sync', headers=pm_headers, json={'ops': [{'type': 'checkitem', 'client_uuid': str(uuid4()), 'payload': {'project_id': pid, 'check_item_id': cid, 'body': {'is_done': True, 'version': 0}}}]})
    assert response.status_code == 200 and len(response.json()['rejected']) == 1
    with SessionLocal() as db:
        assert not db.get(CheckItem, cid).is_done and not db.get(Task, tid).manually_completed
        assert not db.query(DailyProgress).filter_by(task_id=tid).count()
    # Documents and actual issue reports remain available before field execution.
    assert upload(client, pm_headers, pid).status_code == 200
    response = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '提前发现问题', 'description': '', 'issue_type': 'hardware', 'client_uuid': str(uuid4())})
    assert response.status_code == 200, response.text


def test_private_document_names_and_review_notes_do_not_leak_through_manifest_history_or_project(client, pm_headers, admin_headers):
    pid, doc = scope(client, pm_headers)
    assert client.put(f'/api/projects/{pid}/documents/{doc["id"]}/confidentiality', headers=pm_headers, json={'confidential': True, 'confidential_user_ids': [], 'version': doc['version']}).status_code == 200
    result = preview(client, admin_headers, pid)
    assert doc['name'] not in str(result) and doc['id'] not in str(result)
    assert result['entry_unmet'][0]['restricted'] is True
    assert confirm(client, pm_headers, pid, notes=f'保密细节 {doc["name"]}').status_code == 200
    response = client.get(f'/api/projects/{pid}/documents/dispatch-review/history', headers=admin_headers)
    assert response.status_code == 200 and doc['name'] not in response.text and '保密细节' not in response.text
    response = client.get(f'/api/projects/{pid}', headers=admin_headers)
    assert '保密细节' not in response.text


def test_old_preparation_review_endpoints_are_retired_and_new_preview_writes_no_business_facts(client, pm_headers):
    pid, doc = scope(client, pm_headers)
    before = preview(client, pm_headers, pid)
    for path, body in [('confirm-ready', {}), ('review', {}), ('review/confirm', {'conclusion': 'risky', 'notes': '旧接口'})]:
        response = client.post(f'/api/projects/{pid}/preparations/{path}', headers=pm_headers, json=body)
        assert response.status_code == 410, response.text
    assert client.get(f'/api/projects/{pid}/preparations/reviews', headers=pm_headers).status_code == 410
    assert preview(client, pm_headers, pid) == before
    with SessionLocal() as db:
        assert db.query(ProjectReadinessReview).filter_by(project_id=pid).count() == 0
        assert db.get(Project, pid).status == 'ready'


def test_authorized_old_period_cleanup_retains_submission_but_normal_missing_original_does_not(client, admin_headers):
    from tests.test_storage_cleanup import weekly, preview as cleanup_preview, confirm as cleanup_confirm
    from app.services.dispatch_review import manifest
    from app import config
    pid, rows=weekly(client,admin_headers)
    plan=cleanup_preview(client,admin_headers,pid)
    assert cleanup_confirm(client,admin_headers,pid,plan).status_code==200
    with SessionLocal() as db:
        state=manifest(db,db.get(Project,pid))
        old=next(row for row in state['met'] if row['id']==rows[0][0])
        assert old['retained_by_policy'] and not old['original_available']
        (config.UPLOAD_DIR/rows[-1][2]).unlink()
        state=manifest(db,db.get(Project,pid))
        assert any(row['id']==rows[-1][0] for row in state['entry_unmet'])
        assert all(row['id']!=rows[0][0] for row in state['entry_unmet'])


def test_public_requirement_does_not_expose_its_independently_private_original_metadata(client, pm_headers, admin_headers):
    pid, doc=scope(client,pm_headers)
    response=upload(client,pm_headers,pid,[doc['id']],confidential='true',confidential_user_ids='[]')
    assert response.status_code==200,response.text
    asset=response.json()['file']
    state=preview(client,admin_headers,pid)
    assert doc['name'] in str(state) and asset['id'] not in str(state) and asset['sha256'] not in str(state)
    projected=next(row for row in state['met'] if row['id']==doc['id'])
    assert projected['file_restricted'] and projected['attachment_id'] is None and projected['sha256'] is None
