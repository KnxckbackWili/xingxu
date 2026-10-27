"""持久 AI 作业历史的隔离、过期、幂等和限流。"""

from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.time_utils import utcnow

def test_ai_job_lifecycle_survives_session_restart(client):
    """create → running → completed 各步独立开新会话，模拟任意 worker/重启后仍可读到结果。"""
    from app.services import ai_jobs
    uid = 'user-ai-lifecycle-1'
    job = ai_jobs.create_job(uid, '整理一下')
    assert job['status'] == 'queued'
    assert job['percent'] == 2
    assert 'id' in job and 'user_id' not in job and ('updated_at' not in job)
    ai_jobs.set_job(job['id'], status='running', percent=40, stage='parse', message='解析中')
    got = ai_jobs.get_job(job['id'], uid)
    assert got['status'] == 'running'
    assert got['percent'] == 40
    assert got['stage'] == 'parse'
    ai_jobs.set_job(job['id'], status='completed', percent=100, result={'ok': True, 'count': 3}, message='完成')
    got2 = ai_jobs.get_job(job['id'], uid)
    assert got2['status'] == 'completed'
    assert got2['percent'] == 100
    assert got2['result'] == {'ok': True, 'count': 3}

def test_ai_job_owner_scoped_404(client):
    from app.services import ai_jobs
    job = ai_jobs.create_job('user-owner-a', 'hi')
    with pytest.raises(HTTPException) as ei:
        ai_jobs.get_job(job['id'], 'user-owner-b')
    assert ei.value.status_code == 404

def test_ai_job_stale_running_becomes_failed(client):
    """进程崩溃留下的 queued/running job：读取时按 updated_at 陈旧阈值置为显式 failed。"""
    from app.db import SessionLocal
    from app.models import AiJob
    from app.services import ai_jobs
    uid = 'user-ai-stale-1'
    job = ai_jobs.create_job(uid, '执行中断的任务')
    db = SessionLocal()
    try:
        row = db.get(AiJob, job['id'])
        row.status = 'running'
        row.updated_at = utcnow() - timedelta(minutes=40)
        db.commit()
    finally:
        db.close()
    got = ai_jobs.get_job(job['id'], uid)
    assert got['status'] == 'failed'
    assert got['stage'] == 'failed'
    assert '中断' in (got['error'] or '')

def test_ai_job_expired_cleaned_and_404(client):
    """超过 TTL 的 job 在新 job 创建时被清理，读取旧 id → 404（不泄漏内存/不无限轮询）。"""
    from app.db import SessionLocal
    from app.models import AiJob
    from app.services import ai_jobs
    uid = 'user-ai-ttl-1'
    old = ai_jobs.create_job(uid, '会过期的任务')
    db = SessionLocal()
    try:
        row = db.get(AiJob, old['id'])
        row.updated_at = utcnow() - timedelta(hours=3)
        db.commit()
    finally:
        db.close()
    ai_jobs.create_job(uid, '新任务触发清理')
    with pytest.raises(HTTPException) as ei:
        ai_jobs.get_job(old['id'], uid)
    assert ei.value.status_code == 404

def test_ai_job_rate_limit_rejects_excess_requests(client):
    from app.services import ai_jobs
    ai_jobs.reset_ai_rate_limits()
    u = SimpleNamespace(id='user-ai-rl-1')
    for _ in range(12):
        ai_jobs.rate_limit(u)
    with pytest.raises(HTTPException) as ei:
        ai_jobs.rate_limit(u)
    assert ei.value.status_code == 429
