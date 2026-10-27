"""AI 作业历史的并发完成及延迟重试保护。"""

from datetime import timedelta
import pytest
from fastapi import HTTPException
from app.db import SessionLocal
from app.models import AiJob
from app.services import ai_jobs
from app.time_utils import utcnow


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed"])
def test_expired_job_is_404_without_another_job_triggering_cleanup(client, status):
    job = ai_jobs.create_job("user-admin-001", "Expires independently")
    with SessionLocal() as db:
        row = db.get(AiJob, job["id"])
        row.status = status
        row.updated_at = utcnow() - timedelta(seconds=ai_jobs._JOB_TTL_SECONDS + 5)
        db.commit()
    with pytest.raises(HTTPException) as caught:
        ai_jobs.get_job(job["id"], "user-admin-001")
    assert caught.value.status_code == 404


@pytest.mark.parametrize("late_status", ["running", "completed", "failed"])
def test_completed_job_is_not_overwritten_by_delayed_worker(client, late_status):
    job = ai_jobs.create_job("user-admin-001", "Stable completed result")
    ai_jobs.set_job(job["id"], status="completed", stage="completed", percent=100, result={"draft": "valid"})
    before = ai_jobs.get_job(job["id"], "user-admin-001")
    ai_jobs.set_job(job["id"], status=late_status, stage="late", percent=20,
                    result={"draft": "late duplicate"}, error="late failure")
    assert ai_jobs.get_job(job["id"], "user-admin-001") == before


def test_stale_failed_job_cannot_be_resurrected_by_late_success(client):
    job = ai_jobs.create_job("user-admin-001", "Interrupted job")
    with SessionLocal() as db:
        row = db.get(AiJob, job["id"])
        row.status = "running"
        row.updated_at = utcnow() - timedelta(seconds=ai_jobs._STALE_JOB_SECONDS + 5)
        db.commit()
    failed = ai_jobs.get_job(job["id"], "user-admin-001")
    assert failed["status"] == "failed"
    ai_jobs.set_job(job["id"], status="completed", stage="completed", percent=100, result={"draft": "late"})
    assert ai_jobs.get_job(job["id"], "user-admin-001") == failed


@pytest.mark.parametrize('revocation',['account','capability','budget'])
def test_queued_retired_organize_never_contacts_provider(client,pm_headers,monkeypatch,revocation):
    from app.routers.ai_projects import _run_organize_job,OrganizeBody
    calls=[]
    monkeypatch.setattr('app.services.ai_project_assistant.organize_domain',lambda *args,**kwargs:calls.append(args))
    job=ai_jobs.create_job('user-pm-001','old queued work')
    _run_organize_job(job['id'],OrganizeBody(skill='planning'),'user-pm-001')
    assert ai_jobs.get_job(job['id'],'user-pm-001')['status']=='failed' and calls==[]


def test_stale_poll_snapshot_cannot_overwrite_concurrent_completion(client):
    job = ai_jobs.create_job("user-admin-001", "Completion races stale poll")
    with SessionLocal() as db:
        row = db.get(AiJob, job["id"])
        row.status = "running"
        row.updated_at = utcnow() - timedelta(minutes=40)
        db.commit()
    with SessionLocal() as polling_db:
        stale_snapshot = polling_db.get(AiJob, job["id"])
        ai_jobs.set_job(job["id"], status="completed", stage="completed", percent=100, result={"answer": "Finished"})
        ai_jobs._mark_stale_failed(polling_db, stale_snapshot)
        assert stale_snapshot.status == "completed"
        assert stale_snapshot.result == {"answer": "Finished"}
        assert stale_snapshot.error is None


def test_retired_organize_cannot_retry_new_job_and_completed_history_is_noop(client,pm_headers):
    from app.routers.ai_projects import _run_organize_job,OrganizeBody
    for _ in range(2):
        assert client.post('/api/ai-projects/organize/jobs',headers=pm_headers,json={'skill':'planning'}).status_code==410
    job=ai_jobs.create_job('user-pm-001','completed history')
    ai_jobs.set_job(job['id'],status='completed',percent=100,result={'draft':'original owner text'})
    before=ai_jobs.get_job(job['id'],'user-pm-001')
    _run_organize_job(job['id'],OrganizeBody(),'user-pm-001')
    assert ai_jobs.get_job(job['id'],'user-pm-001')==before
