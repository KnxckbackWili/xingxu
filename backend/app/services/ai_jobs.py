"""AI 任务共享基建：每用户限流（跨 worker 共享）+ DB-backed job 持久化。

结构化项目、排程、物品、问题和交接整理共用限流与持久任务表。

HYPE-99：job 从进程内内存态改为落库（ai_jobs 表）——
- 生产 WEB_CONCURRENCY=2 时，job 由任意 worker 创建/执行/轮询都不会跨进程 404；
- 进程重启后 completed 结果在 TTL（1 小时）内仍可读；
- 被中断的 queued/running job（updated_at 超过陈旧阈值）在读取时自动置为 failed，
  前端能拿到显式失败态并重新发起，绝不无限转圈。

限流（HYPE-99）：SQLite（单进程测试/本地）保留进程内滑动窗口，行为不变；
PostgreSQL（生产多 worker）用 ai_rate_limit_buckets 表按 scope 保存共享计数。
"""

import time
import uuid
from collections import deque
from datetime import timedelta
from threading import Lock

from fastapi import HTTPException

from app.models import User
from app.time_utils import utcnow

_RATE_LIMIT_MAX = 12
_RATE_LIMIT_WINDOW_MINUTES = 10
_JOB_TTL_SECONDS = 3600
_MAX_JOBS_PER_USER = 100
# queued/running 超过该时长无进度更新 → 视为执行中断（进程被杀/崩溃），读取时置 failed
_STALE_JOB_SECONDS = 30 * 60


# 进程内限流（SQLite/单进程路径）
_struct_calls: dict[str, deque] = {}
_struct_lock = Lock()


def _consume_memory(
    bucket: dict[str, deque], lock: Lock, user_id: str, limit: int, window_minutes: int
) -> None:
    """SQLite/单进程滑动窗口限流（原实现）。"""
    from app.db import _is_sqlite

    if not _is_sqlite:
        return
    now = utcnow()
    cutoff = now - timedelta(minutes=window_minutes)
    with lock:
        stamps = bucket.setdefault(user_id, deque())
        while stamps and stamps[0] < cutoff:
            stamps.popleft()
        if len(stamps) >= limit:
            raise HTTPException(status_code=429, detail="AI 调用过于频繁，请稍后再试")
        stamps.append(now)


def _pg_ai_consume(scope: str, user_id: str, limit: int, window_minutes: int) -> None:
    """PostgreSQL 共享计数：按 用户×scope×bucket×window 原子递增，多 worker 共用额度。

    实现与 app/services/rate_limit.py 的 _pg_consume 同构；多一层 scope 让结构化整理
    与多轮对话在同一窗口下互不覆盖。
    """
    from sqlalchemy import text
    from app.db import SessionLocal

    window_sec = window_minutes * 60
    db = SessionLocal()
    try:
        now_ts = int(time.time())
        bucket = now_ts // window_sec
        now = utcnow()
        # 清理过期桶（当前 + 上一桶之外的全部删除）。`window` 是 PG 保留字，必须双引号。
        db.execute(
            text(
                "DELETE FROM ai_rate_limit_buckets WHERE user_id = :uid AND scope = :scope "
                'AND "window" = :window AND bucket < :min_bucket'
            ),
            {
                "uid": user_id,
                "scope": scope,
                "window": window_sec,
                "min_bucket": bucket - 1,
            },
        )
        # 幂等建行（并发下只有一个 worker 插入成功）
        db.execute(
            text(
                "INSERT INTO ai_rate_limit_buckets "
                '(id, user_id, scope, bucket, "window", count, created_at, updated_at) '
                "VALUES (:id, :uid, :scope, :bucket, :window, 0, :now, :now) "
                'ON CONFLICT (user_id, scope, bucket, "window") DO NOTHING'
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "scope": scope,
                "bucket": bucket,
                "window": window_sec,
                "now": now,
            },
        )
        db.commit()
        # 原子递增：恰好 limit 次成功，超出返回空 → 429
        row = db.execute(
            text(
                "UPDATE ai_rate_limit_buckets SET count = count + 1, updated_at = :now "
                "WHERE user_id = :uid AND scope = :scope AND bucket = :bucket "
                'AND "window" = :window AND count < :limit RETURNING count'
            ),
            {
                "uid": user_id,
                "scope": scope,
                "bucket": bucket,
                "window": window_sec,
                "limit": limit,
                "now": now,
            },
        ).fetchone()
        db.commit()
        if row is None:
            raise HTTPException(status_code=429, detail="AI 调用过于频繁，请稍后再试")
    finally:
        db.close()


def rate_limit(user: User) -> None:
    """每用户限流（AI 各入口共享同一 struct 桶）。"""
    from app.db import _is_sqlite

    if _is_sqlite:
        _consume_memory(
            _struct_calls,
            _struct_lock,
            user.id,
            _RATE_LIMIT_MAX,
            _RATE_LIMIT_WINDOW_MINUTES,
        )
    else:
        _pg_ai_consume("struct", user.id, _RATE_LIMIT_MAX, _RATE_LIMIT_WINDOW_MINUTES)


# ===== DB-backed job registry =====


def _job_db():
    from app.db import SessionLocal

    return SessionLocal()


def _public(job) -> dict:
    """job 模型 → API dict（剥离内部 user_id/updated_at/时间戳）。"""
    return {
        "id": job.id,
        "status": job.status,
        "percent": job.percent,
        "stage": job.stage,
        "message": job.message or "",
        "result": job.result,
        "error": job.error,
    }


def _enforce_caps(db, user_id: str) -> None:
    """TTL 清理 + 每用户条数上限：过期 job 先删，再按最旧裁掉超限部分。"""
    from app.models import AiJob

    cutoff = utcnow() - timedelta(seconds=_JOB_TTL_SECONDS)
    stale = (
        db.query(AiJob.id)
        .filter(AiJob.user_id == user_id, AiJob.updated_at < cutoff)
        .all()
    )
    if stale:
        db.query(AiJob).filter(AiJob.id.in_([r[0] for r in stale])).delete(
            synchronize_session=False
        )
    recent = (
        db.query(AiJob.id)
        .filter(AiJob.user_id == user_id)
        .order_by(AiJob.updated_at.desc())
        .offset(_MAX_JOBS_PER_USER)
        .all()
    )
    if recent:
        db.query(AiJob).filter(AiJob.id.in_([r[0] for r in recent])).delete(
            synchronize_session=False
        )


def _mark_stale_failed(db, job) -> None:
    """中断检测：queued/running 超过陈旧阈值无进度 → 置为显式 failed（可重新发起）。"""
    from app.models import AiJob

    if job.status not in ("queued", "running"):
        return
    stale_before = utcnow() - timedelta(seconds=_STALE_JOB_SECONDS)
    if job.updated_at is not None and job.updated_at < stale_before:
        # Another worker may have completed or reported progress since this
        # poll read the row. Only fail the still-stale active state atomically.
        db.query(AiJob).filter(
            AiJob.id == job.id,
            AiJob.status.in_(("queued", "running")),
            AiJob.updated_at < stale_before,
        ).update(
            {
                "status": "failed",
                "stage": "failed",
                "result": None,
                "error": "任务执行中断（进程重启或超时），请重新发起",
                "updated_at": utcnow(),
            },
            synchronize_session=False,
        )
        db.commit()
        db.refresh(job)


def create_job(user_id: str, message: str, *, kind: str = "generic") -> dict:
    """新建一个 queued job 并返回（DB-backed，多 worker 可读）。"""
    from app.models import AiJob

    db = _job_db()
    try:
        job = AiJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            kind=kind,
            status="queued",
            percent=2,
            stage="queued",
            message=message,
            result=None,
            error=None,
        )
        db.add(job)
        db.flush()
        _enforce_caps(db, user_id)
        db.commit()
        db.refresh(job)
        return _public(job)
    finally:
        db.close()


def set_job(job_id: str, **changes) -> None:
    """更新 job（写库；job 已过期/被清理则忽略）。"""
    from app.models import AiJob

    allowed = {"status", "percent", "stage", "message", "result", "error"}
    db = _job_db()
    try:
        # Terminal results are immutable. Guard in the UPDATE itself so late
        # progress, duplicate workers and stale detection cannot race past a
        # read-then-write check and resurrect/replace a finished job.
        values = {key: value for key, value in changes.items() if key in allowed}
        values["updated_at"] = utcnow()
        if values.get("status") == "completed":
            values["error"] = None
        elif values.get("status") == "failed":
            values["result"] = None
        db.query(AiJob).filter(
            AiJob.id == job_id,
            AiJob.status.in_(("queued", "running")),
            AiJob.updated_at >= utcnow() - timedelta(seconds=_JOB_TTL_SECONDS),
        ).update(values, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def get_job(job_id: str, user_id: str) -> dict:
    """按 owner 读取 job；不存在/过期/非本人 → 404；中断 job 置为 failed 再返回。"""
    from app.models import AiJob

    db = _job_db()
    try:
        job = (
            db.query(AiJob).filter(AiJob.id == job_id, AiJob.user_id == user_id).first()
        )
        if job is None or (
            job.updated_at is not None
            and job.updated_at < utcnow() - timedelta(seconds=_JOB_TTL_SECONDS)
        ):
            raise HTTPException(status_code=404, detail="AI 整理任务不存在或已过期")
        _mark_stale_failed(db, job)
        return _public(job)
    finally:
        db.close()


def reset_ai_rate_limits() -> None:
    """清空 AI 限流状态（测试隔离用）。SQLite 清内存；PG 清共享表。"""
    with _struct_lock:
        _struct_calls.clear()
    from app.db import _is_sqlite

    if not _is_sqlite:
        from sqlalchemy import text
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM ai_rate_limit_buckets"))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
