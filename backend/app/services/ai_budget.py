"""AI 用量预算护栏。

按自然月统计外部 AI 调用（请求数 + 估算 token 数），超限后降级提示、不发起外部调用。
计数存 `ai_usage_ledger` 表（PG 多 worker 共享），配合 `create_all` 自动建表。

预算上限来自环境变量：
- `AGVPM_AI_MONTHLY_REQUESTS`（0=不限制）
- `AGVPM_AI_MONTHLY_TOKENS`（0=不限制）

token 为**估算值**（`len(text)//4`），用于成本护栏的近似计量；精确计费以供应商账单为准。
"""

import time
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import config
from app.db import _is_sqlite
from app.models import AiUsageLedger
from app.time_utils import utcnow


def current_month() -> str:
    """本地时区下的自然月 "YYYY-MM"。"""
    return time.strftime("%Y-%m")


def limits() -> dict:
    return {
        "requests": max(0, config.AI_MONTHLY_REQUESTS),
        "tokens": max(0, config.AI_MONTHLY_TOKENS),
    }


def get_usage(db: Session) -> dict:
    row = (
        db.query(AiUsageLedger)
        .filter(AiUsageLedger.month == current_month())
        .first()
    )
    if row is None:
        return {"month": current_month(), "requests": 0, "tokens": 0}
    return {"month": row.month, "requests": row.requests or 0, "tokens": row.tokens or 0}


def budget_status(db: Session) -> dict:
    """供 /status 与前端展示：限额、当月用量、是否已封顶。"""
    cfg = limits()
    used = get_usage(db)
    blocked = False
    reason = ""
    if cfg["requests"] and used["requests"] >= cfg["requests"]:
        blocked, reason = True, "月度请求次数已达上限"
    elif cfg["tokens"] and used["tokens"] >= cfg["tokens"]:
        blocked, reason = True, "月度 token 用量已达上限"
    return {
        "enabled": bool(cfg["requests"] or cfg["tokens"]),
        "limits": cfg,
        "usage": used,
        "blocked": blocked,
        "reason": reason,
    }


def check_quota(db: Session) -> None:
    """AI 调用前检查：超限则 429 拒绝，不发外部请求。"""
    if not (config.AI_MONTHLY_REQUESTS or config.AI_MONTHLY_TOKENS):
        return
    cfg = limits()
    used = get_usage(db)
    if cfg["requests"] and used["requests"] >= cfg["requests"]:
        raise HTTPException(
            status_code=429,
            detail=f"AI 月度请求次数已达上限（{used['requests']}/{cfg['requests']}），请下月再试或联系管理员调整预算",
        )
    if cfg["tokens"] and used["tokens"] >= cfg["tokens"]:
        raise HTTPException(
            status_code=429,
            detail=f"AI 月度 token 用量已达上限（{used['tokens']}/{cfg['tokens']}），请下月再试或联系管理员调整预算",
        )


def estimate_tokens(text: str) -> int:
    """中英混排估算：1 token ≈ 4 字符（仅用于护栏计量，非计费依据）。"""
    return len(text or "") // 4


def record_usage(db: Session, requests: int = 1, tokens: int = 0) -> dict:
    """AI 调用成功后记账（多 worker 安全的原子递增 upsert）。

    PG 与 SQLite 均走 `INSERT ... ON CONFLICT (month) DO UPDATE SET
    列 = 列 + 增量`，由数据库在单条语句内完成递增，避免「读-改-写」
    在并发下互相覆盖丢计数；同一自然月各 worker 共享一行累计。
    """
    month = current_month()
    delta_r = max(0, int(requests))
    delta_t = max(0, int(tokens))
    if not delta_r and not delta_t:
        return get_usage(db)

    if _is_sqlite:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(AiUsageLedger).values(month=month, requests=delta_r, tokens=delta_t)
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(AiUsageLedger).values(month=month, requests=delta_r, tokens=delta_t)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AiUsageLedger.month],
        set_={
            AiUsageLedger.requests: AiUsageLedger.requests + stmt.excluded.requests,
            AiUsageLedger.tokens: AiUsageLedger.tokens + stmt.excluded.tokens,
            AiUsageLedger.updated_at: utcnow(),
        },
    )
    db.execute(stmt)
    db.commit()
    return get_usage(db)


def record_usage_standalone(requests: int = 1, tokens: int = 0) -> dict:
    """后台任务（无请求级 session）独立开 session 记账。失败不抛出，仅日志。"""
    import logging

    from app.db import SessionLocal

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        return record_usage(db, requests=requests, tokens=tokens)
    except Exception as error:  # noqa: BLE001 —— 记账失败不应使 AI 结果作废
        logger.warning("AI 用量记账失败（不影响本次结果）: %s", error)
        return {"month": current_month(), "requests": 0, "tokens": 0}
    finally:
        db.close()
