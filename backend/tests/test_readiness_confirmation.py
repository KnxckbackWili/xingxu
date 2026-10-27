"""Reasoned stage-five exceptions remain visible without changing source evidence."""
from tests.lifecycle_helpers import versioned
from app.db import SessionLocal
from app.models import Project, ProjectDocument, ProjectDocumentDefinition, ProjectReadinessReview
from tests.test_dispatch_review_t29 import scope, preview, confirm, requirement
from tests.test_project_documents import view


def test_forced_confirmation_is_visible_with_unfinished_items(client, pm_headers):
    pid, doc = scope(client, pm_headers)
    result = confirm(client, pm_headers, pid)
    assert result.status_code == 200 and result.json()['summary']['state'] == '已批准风险进场'
    assert result.json()['summary']['blocked'] == 1 and result.json()['summary']['entry_confirmed']
    assert next(row for row in view(client, pm_headers, pid)['documents'] if row['id'] == doc['id'])['status'] == 'pending'


def test_unfinished_cannot_be_silently_confirmed_and_force_requires_reason(client, pm_headers):
    pid, _ = scope(client, pm_headers)
    assert confirm(client, pm_headers, pid, conclusion='ready').status_code == 400
    assert confirm(client, pm_headers, pid, notes='  ').status_code == 400
    path = f'/api/projects/{pid}/documents/dispatch-review'
    assert client.get(path+'/history', headers=pm_headers).json() == []
    assert client.post(path+'/confirm', headers=pm_headers).status_code == 422


def test_force_snapshot_and_new_omission_require_a_new_confirmation(client, pm_headers):
    pid, doc = scope(client, pm_headers)
    reason = '现场受控，由负责人次日补齐'
    assert confirm(client, pm_headers, pid, notes=reason).status_code == 200
    with SessionLocal() as db:
        review = db.query(ProjectReadinessReview).filter_by(project_id=pid).one()
        assert review.notes == reason
        assert next(row for row in review.snapshot if row['id'] == doc['id'])['status'] == 'pending'
    changed = client.put(f'/api/projects/{pid}/documents/{doc["id"]}', headers=pm_headers, json={'status': 'waived', 'reason': '合同明确不适用', 'version': doc['version']})
    assert changed.status_code == 200
    from app.services.dispatch_review import summary
    with SessionLocal() as db:
        assert summary(db, db.get(Project,pid))['entry_confirmed']
    requirement(client, pm_headers, pid, '新发生的必需资料')
    with SessionLocal() as db:
        actual=summary(db, db.get(Project,pid)); assert actual['void'] and not actual['entry_confirmed']


def test_stale_manifest_rejected_and_non_applicable_items_can_confirm(client, pm_headers):
    pid, doc = scope(client, pm_headers)
    old = preview(client, pm_headers, pid)
    result=client.put(f'/api/projects/{pid}/documents/{doc["id"]}', headers=pm_headers, json={'status': 'waived', 'reason': '客户无需本项', 'version': doc['version']})
    assert result.status_code == 200
    assert confirm(client, pm_headers, pid, token=old['review_token']).status_code == 409
    result=confirm(client, pm_headers, pid, conclusion='ready')
    assert result.status_code == 200 and result.json()['summary']['state_key'] == 'ready'


def test_empty_checklist_is_shown_as_missing_and_requires_explanation(client, pm_headers):
    pid, _ = scope(client, pm_headers)
    with SessionLocal() as db:
        db.query(ProjectDocument).filter_by(project_id=pid,stage_key='5').delete(synchronize_session=False)
        db.query(ProjectDocumentDefinition).filter_by(project_id=pid,stage_key='5').delete(synchronize_session=False)
        db.commit()
    assert preview(client, pm_headers, pid)['missing']
    assert confirm(client, pm_headers, pid, conclusion='ready').status_code == 400
    result=confirm(client, pm_headers, pid, notes='本次仅远程支持，已明确核对不安排现场进场')
    assert result.status_code == 200 and result.json()['summary']['entry_confirmed']


def test_worker_cannot_force_confirmation(client, pm_headers, worker_headers):
    pid, _ = scope(client, pm_headers)
    token=preview(client, pm_headers, pid)['review_token']
    client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members':['user-worker-001']}))
    assert confirm(client, worker_headers, pid, token=token).status_code == 403
