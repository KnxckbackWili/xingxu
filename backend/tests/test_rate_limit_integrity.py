"""导出限流与 PostgreSQL 共享计数边界。"""

import pytest
from fastapi import HTTPException
from sqlalchemy import text

def _freeze_rate_clock(monkeypatch):
    """Keep all requests in one fixed window; a slow run must not roll into a fresh bucket mid-test."""
    import time as real
    from types import SimpleNamespace
    from app.services import rate_limit as rl
    frozen = real.time()
    monkeypatch.setattr(rl, 'time', SimpleNamespace(time=lambda: frozen, monotonic=lambda: frozen))


def test_export_rate_limited(client, pm_headers, monkeypatch):
    _freeze_rate_clock(monkeypatch)
    """B5：导出接口按用户限流，超限返回 429。"""
    pid = client.post('/api/projects', headers=pm_headers, json={'name': '导出限流项目', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}).json()['id']
    ok = 0
    for i in range(11):
        r = client.get(f'/api/projects/{pid}/export/excel', headers=pm_headers)
        if r.status_code == 200:
            ok += 1
        elif r.status_code == 429:
            break
    assert ok == 10, f'应前 10 次成功，实际 {ok}'

def test_pg_shared_rate_limit_atomic(client, monkeypatch):
    """T006：PG 共享计数路径（SQLite 上等价 SQL 验证）——同用户前 10 次成功第 11 次 429、异用户隔离、窗口滚动重置。"""
    from app.services import rate_limit as rl
    monkeypatch.setattr(rl, '_is_sqlite', False)
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text('DELETE FROM rate_limit_buckets'))
        db.commit()
        for _ in range(10):
            rl._pg_consume(db, 'user-x', 10, 300)
        with pytest.raises(HTTPException) as ei:
            rl._pg_consume(db, 'user-x', 10, 300)
        assert ei.value.status_code == 429
        rl._pg_consume(db, 'user-y', 10, 300)
        rl._pg_consume(db, 'user-y', 10, 300)
        db.execute(text("UPDATE rate_limit_buckets SET bucket = bucket - 2 WHERE user_id = 'user-x'"))
        db.commit()
        rl._pg_consume(db, 'user-x', 10, 300)
        db.execute(text('DELETE FROM rate_limit_buckets'))
        db.commit()
    finally:
        db.close()

def test_export_rate_limited_still_ok(client, pm_headers, monkeypatch):
    _freeze_rate_clock(monkeypatch)
    """T006：SQLite 路径导出限流行为不回退（验证超限边界）。"""
    pid = client.post('/api/projects', headers=pm_headers, json={'name': '导出限流回归', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}).json()['id']
    ok = 0
    for i in range(11):
        r = client.get(f'/api/projects/{pid}/export/excel', headers=pm_headers)
        if r.status_code == 200:
            ok += 1
        elif r.status_code == 429:
            break
    assert ok == 10, f'应前 10 次成功，实际 {ok}'

def test_pg_sql_quotes_reserved_word_window():
    """T006：PG 保留字防护——rate_limit_buckets.window 在原生 SQL 中必须双引号。

    `window` 是 PostgreSQL 保留字，SQLite 不限；此用例防止将来在 raw SQL 里
    裸写 window 列导致生产 PG 500（本 bug 由 8002 并发实测捕获）。
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'app' / 'services' / 'rate_limit.py'
    text_src = src.read_text()
    buggy = ['window = :window', 'bucket, window', '(user_id, bucket, window)', 'AND window ']
    for b in buggy:
        assert b not in text_src, f'rate_limit.py 存在未加引号的 window 列引用: {b}'
    assert '\\"window\\" = :window' in text_src
    assert 'bucket, \\"window\\"' in text_src
    assert '(user_id, bucket, \\"window\\")' in text_src
