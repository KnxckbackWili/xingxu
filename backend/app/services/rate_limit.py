"""通用限流：导出等昂贵接口按用户限流（B5）。

单容器多 worker（WEB_CONCURRENCY>=2）下，进程内计数器会让全局额度放大为
worker 数 × 单进程额度，且容器重启即绕过窗口。改为 PostgreSQL 共享计数
（T006）：按 用户×窗口×时间桶 在库内原子递增，多 worker 共用同一额度，
重启不绕过、不同用户额度隔离，且不引入额外容器。

- SQLite（单进程测试/本地）：保留原内存滑动窗口，行为不变。
- PostgreSQL（生产多 worker）：库内固定窗口桶 + 原子 UPDATE RETURNING。
"""

import time
import threading
from collections import defaultdict, deque

from fastapi import HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import _is_sqlite, get_db
from app.deps import get_current_user
from app.models import User
from app.time_utils import utcnow


_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)

# 默认：每 5 分钟最多 15 次
_DEFAULT_WINDOW = 300.0
_DEFAULT_LIMIT = 15


def _memory_consume(user_id: str, limit: int, window: float) -> None:
    """SQLite/单进程：内存滑动窗口（原实现）。"""
    key = user_id
    now = time.monotonic()
    with _lock:
        stamps = _hits[key]
        while stamps and now - stamps[0] > window:
            stamps.popleft()
        if len(stamps) >= limit:
            raise HTTPException(status_code=429,
                                detail=f"操作过于频繁，请稍后再试（{int(window)} 秒内最多 {limit} 次）")
        stamps.append(now)
        if len(_hits) > 10_000:
            # 防止 key 无限膨胀
            for k in list(_hits.keys()):
                if k != key and not _hits[k]:
                    _hits.pop(k, None)


def _pg_consume(db: Session, user_id: str, limit: int, window: int) -> None:
    """PostgreSQL 共享计数（T006）：固定窗口桶 + 原子递增，多 worker 共用同一额度。

    实现要点：
    1. 桶号 bucket = int(now // window)，窗口滚动后新桶自动归零；
    2. INSERT ... ON CONFLICT DO NOTHING 幂等建行；
    3. UPDATE ... WHERE count < :limit RETURNING count 原子递增——
       PG 行锁保证并发下恰好 limit 次成功，第 limit+1 次起返回空 → 429；
    4. 顺带清理该用户早于上一桶的过期桶，避免无限膨胀。
    """
    now_ts = int(time.time())
    bucket = now_ts // window
    now = utcnow()

    # 清理过期桶（当前桶 + 上一桶之外的全部删除）。
    # 注意：`window` 是 PostgreSQL 保留字，必须用双引号引用列名。
    db.execute(text(
        "DELETE FROM rate_limit_buckets "
        "WHERE user_id = :uid AND \"window\" = :window AND bucket < :min_bucket"
    ), {"uid": user_id, "window": window, "min_bucket": bucket - 1})

    # 幂等建行（并发下只有一个线程插入成功）
    import uuid
    db.execute(text(
        "INSERT INTO rate_limit_buckets (id, user_id, bucket, \"window\", count, created_at, updated_at) "
        "VALUES (:id, :uid, :bucket, :window, 0, :now, :now) "
        "ON CONFLICT (user_id, bucket, \"window\") DO NOTHING"
    ), {"id": str(uuid.uuid4()), "uid": user_id, "bucket": bucket,
        "window": window, "now": now})
    db.commit()

    # 原子递增：恰好 limit 次成功，超出返回空
    row = db.execute(text(
        "UPDATE rate_limit_buckets SET count = count + 1, updated_at = :now "
        "WHERE user_id = :uid AND bucket = :bucket AND \"window\" = :window AND count < :limit "
        "RETURNING count"
    ), {"uid": user_id, "bucket": bucket, "window": window,
        "limit": limit, "now": now}).fetchone()
    db.commit()

    if row is None:
        raise HTTPException(status_code=429,
                            detail=f"操作过于频繁，请稍后再试（{window} 秒内最多 {limit} 次）")


def rate_limit(limit: int = _DEFAULT_LIMIT, window: float = _DEFAULT_WINDOW):
    """FastAPI 依赖工厂：按当前用户限流，超出抛 429。

    SQLite → 进程内滑动窗口；PostgreSQL → 库内共享计数（多 worker 共用）。
    """
    def _dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        if _is_sqlite:
            _memory_consume(user.id, int(limit), window)
        else:
            _pg_consume(db, user.id, int(limit), int(window))
        return user
    return _dep


def rate_limit_export():
    """导出接口专用：窗口更宽但频次更严，避免大文件并发放大内存峰值。"""
    return rate_limit(limit=10, window=300.0)


def reset_rate_limits():
    """清空限流状态（测试隔离用）。SQLite 清内存；PG 清共享表。"""
    with _lock:
        _hits.clear()
    if not _is_sqlite:
        from app.db import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM rate_limit_buckets"))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
