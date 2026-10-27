"""AI 用量预算护栏测试（app/services/ai_budget.py + 路由接线）。"""

import pytest
from fastapi import HTTPException


def test_budget_disabled_by_default(client):
    """未配置预算上限时 enabled=False，且不会阻断。"""
    from app.db import SessionLocal
    from app.services.ai_budget import budget_status, check_quota, current_month

    db = SessionLocal()
    try:
        status = budget_status(db)
        assert status["enabled"] is False
        assert status["usage"]["month"] == current_month()
        check_quota(db)  # 不抛
    finally:
        db.close()


def test_record_and_check_quota(client, monkeypatch):
    """按自然月记账：限额内放行，达到上限后 check_quota 抛 429。"""
    import app.config
    from app.db import SessionLocal
    from app.services.ai_budget import check_quota, get_usage, record_usage

    monkeypatch.setattr(app.config, "AI_MONTHLY_REQUESTS", 2)
    monkeypatch.setattr(app.config, "AI_MONTHLY_TOKENS", 0)

    db = SessionLocal()
    try:
        record_usage(db, requests=1, tokens=100)
        assert get_usage(db)["requests"] == 1
        check_quota(db)  # 限额内不抛

        record_usage(db, requests=1, tokens=100)
        assert get_usage(db)["requests"] == 2
        with pytest.raises(HTTPException) as exc:
            check_quota(db)
        assert exc.value.status_code == 429
    finally:
        db.close()


def test_token_limit_blocks(client, monkeypatch):
    """token 上限同样生效。"""
    import app.config
    from app.db import SessionLocal
    from app.services.ai_budget import check_quota, record_usage

    monkeypatch.setattr(app.config, "AI_MONTHLY_REQUESTS", 0)
    monkeypatch.setattr(app.config, "AI_MONTHLY_TOKENS", 10)

    db = SessionLocal()
    try:
        record_usage(db, requests=0, tokens=10)
        with pytest.raises(HTTPException) as exc:
            check_quota(db)
        assert exc.value.status_code == 429
    finally:
        db.close()






def test_status_includes_budget(client, admin_headers):
    """/status 返回 budget 字段（未配置时 enabled=False）。"""
    r = client.get("/api/ai-projects/status", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "budget" in body
    assert body["budget"]["enabled"] is False


def test_concurrent_record_usage_loses_no_increment(client):
    """多 worker 并发记账：原子递增 upsert 保证每笔都累加，不丢计数。

    模拟 PG 多 worker：N 个线程各自独立 session 并发写同一自然月，
    最终 requests/tokens 必须恰好等于 N 次增量之和（读-改-写会互相覆盖）。
    """
    import threading

    from app.db import SessionLocal
    from app.models import AiUsageLedger
    from app.services.ai_budget import current_month, get_usage, record_usage

    N = 24
    db = SessionLocal()
    try:
        # 清空当前月（本用例私有库，仅防御残留）
        db.query(AiUsageLedger).filter(AiUsageLedger.month == current_month()).delete()
        db.commit()
    finally:
        db.close()

    errors = []

    def worker(seed: int):
        try:
            sess = SessionLocal()
            try:
                # 每线程增量不同，验证 tokens 与 requests 都精确累加
                record_usage(sess, requests=1, tokens=100 + seed)
            finally:
                sess.close()
        except Exception as exc:  # noqa: BLE001 —— 线程内收集，断言在 join 后统一抛
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发记账线程异常: {errors}"
    db = SessionLocal()
    try:
        usage = get_usage(db)
        assert usage["requests"] == N
        assert usage["tokens"] == sum(100 + i for i in range(N))
    finally:
        db.close()
