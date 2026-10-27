"""T025: 登录失败限流 PostgreSQL 共享计数回归测试。

背景：登录失败限流原为进程内 `_login_failures`（`auth.py`），多 worker
（WEB_CONCURRENCY>=2）下各记各的，全局额度放大为 worker 数 × 单进程额度，且
容器重启即绕过窗口。T025 复用 T006 共享桶设计：`login_failure_buckets` 表
固定窗口桶 + 原子递增（UPDATE ... WHERE count < :limit RETURNING）。

与导出限流（rate_limit_buckets）不同：仅统计失败；成功登录清空该 key 计数。

本文件验证 PG 路径的 SQL（在 SQLite 上执行等价 SQL，同 T006 测试方式）：
  1. 失败 8 次后第 9 次 429（跨 worker 全局累计的 SQL 基础）；
  2. 不同 key（host:username，即不同客户端/账号）隔离；
  3. 成功登录清空该 key 失败计数；
  4. 窗口滚动后新桶归零；
  5. `window` 保留字在原生 SQL 中必须双引号（防 PG 500，同 T006 防护）。
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import text


def _pg_failed_login(db, key):
    """模拟一次失败登录（PG 路径）：check → 认证失败 → record。限流时抛 429。"""
    from app.routers import auth
    auth._pg_login_check(db, key)
    auth._pg_login_record(db, key, False)


def test_login_limit_pg_9th_429_isolation_success_clear(client, monkeypatch):
    """PG 路径：第 9 次 429 / 不同 key 隔离 / 成功清空 / 窗口滚动重置。"""
    from app.routers import auth
    monkeypatch.setattr(auth, "_is_sqlite", False)
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM login_failure_buckets"))
        db.commit()

        # 前 8 次失败放行（401 语义由调用方决定，这里只验证限流计数）
        for _ in range(8):
            _pg_failed_login(db, "192.168.1.50:admin")
        # 第 9 次 → 429（check 预检命中；即使预检被并发绕过，record 的原子守卫也 429）
        with pytest.raises(HTTPException) as ei:
            _pg_failed_login(db, "192.168.1.50:admin")
        assert ei.value.status_code == 429
        with pytest.raises(HTTPException) as ei:
            auth._pg_login_record(db, "192.168.1.50:admin", False)
        assert ei.value.status_code == 429

        # 不同 key 隔离：同 IP 不同账号 / 同账号不同 IP 均不受 admin@该IP 影响
        _pg_failed_login(db, "192.168.1.50:worker1")
        _pg_failed_login(db, "192.168.1.99:admin")

        # 成功登录清空：清空后该 key 又可失败 8 次再触发 429
        auth._pg_login_record(db, "192.168.1.50:admin", True)
        for _ in range(8):
            _pg_failed_login(db, "192.168.1.50:admin")
        with pytest.raises(HTTPException) as ei:
            _pg_failed_login(db, "192.168.1.50:admin")
        assert ei.value.status_code == 429

        # 窗口滚动：把桶回拨两档 → 新桶归零 → 又可放行（重启等价于新桶的持久化语义）
        db.execute(text("UPDATE login_failure_buckets SET bucket = bucket - 2 WHERE key = '192.168.1.50:admin'"))
        db.commit()
        _pg_failed_login(db, "192.168.1.50:admin")

        db.execute(text("DELETE FROM login_failure_buckets"))
        db.commit()
    finally:
        db.close()


def test_login_limit_memory_path_unchanged(client, monkeypatch):
    """SQLite（单进程）路径不回退：内存滑动窗口第 9 次 429、成功清空。"""
    from app.routers import auth
    # This is a direct unit test of the in-memory limiter, independent of the suite DB.
    key = "127.0.0.1:t025_mem_probe"
    auth._login_failures.clear()
    for _ in range(8):
        auth._mem_record_login(key, False)
    with pytest.raises(HTTPException) as ei:
        auth._mem_check_login_limit(key)
    assert ei.value.status_code == 429
    auth._mem_record_login(key, True)  # 成功登录清空
    auth._mem_check_login_limit(key)   # 不再 429
    auth._login_failures.clear()


def test_login_limit_sql_quotes_reserved_word_window():
    """T025：PG 保留字防护——login_failure_buckets.window 在原生 SQL 中必须双引号。

    `window` 是 PostgreSQL 保留字，SQLite 不限；此用例防止将来在 auth.py 的
    原生 SQL 里裸写 window 列导致生产 PG 500（同 T006 防护，防复现）。
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "app" / "routers" / "auth.py"
    text_src = src.read_text()
    # 未加引号的 window 列引用（buggy 形态），出现任一即失败
    buggy = [
        "window = :window",       # WHERE 比较左值裸写
        "bucket, window",         # INSERT 列清单
        "(key, bucket, window)",  # ON CONFLICT 目标列
        "AND window ",            # WHERE 裸列
    ]
    for b in buggy:
        assert b not in text_src, f"auth.py 存在未加引号的 window 列引用: {b}"
    # 确认已加引号的形态存在（防删除）；源码为 Python 字符串字面量 → 带转义 \"
    assert '\\"window\\" = :window' in text_src
    assert 'bucket, \\"window\\"' in text_src
    assert '(key, bucket, \\"window\\")' in text_src
