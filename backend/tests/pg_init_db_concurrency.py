"""HYPE-72 一审返工：真实 PostgreSQL 双进程首次空库 init_db 并发回归（独立库，不碰生产 agvpm）。

背景：生产以 `uvicorn --workers 2` 运行，每个 worker 的 lifespan 都会调用 init_db()。
SQLAlchemy create_all 是逐表 check-then-CREATE（非 IF NOT EXISTS），两个 worker 同时面对
空库并发建表时，一个 worker 先建，另一个在 CREATE TABLE / pg_type 注册处撞唯一键
（IntegrityError: duplicate key value violates unique constraint "pg_type_typname_nsp_index"），
导致一个 worker 启动失败。init_db 已用固定会话级 advisory lock 串行化
`alembic upgrade head → seed` 完整临界区并在 finally 释放（SQLite 保持无锁原行为）。
本回归用两个独立进程复现「双 worker 首次空库首启」，要求两者均成功。

运行方式（本机 / 容器内均可，先建独立测试库）：
    psql -U <user> -h 127.0.0.1 -d postgres -c "DROP DATABASE IF EXISTS agvpm_pginit"
    psql -U <user> -h 127.0.0.1 -d postgres -c "CREATE DATABASE agvpm_pginit"
    cd backend && SEED_DEMO_USERS=1 DATABASE_URL="postgresql+psycopg2://<user>@127.0.0.1:5432/agvpm_pginit" \\
      python tests/pg_init_db_concurrency.py
    psql -U <user> -h 127.0.0.1 -d postgres -c "DROP DATABASE IF EXISTS agvpm_pginit"

验证内容：
  1. 两个独立进程（spawn 全新解释器，等价于两个 uvicorn worker）同时面对空库调用
     init_db()，均成功退出（无 IntegrityError / 无崩溃）。
  2. 串行化生效：schema 与 seed 恰好一份（feedback 表存在、admin 用户唯一）。
  3. 重复并发 init_db（再次启动 / 重启）保持幂等，不报错。
"""

import multiprocessing as mp
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import User  # noqa: E402
from app.models import Feedback  # noqa: E402,F401 - 确保 feedback 表注册进 metadata

PASS = "✅"
FAIL = "❌"


def _step_ok(msg: str):
    print(f"{PASS} {msg}", flush=True)


def _step_fail(msg: str):
    print(f"{FAIL} {msg}", flush=True)
    raise SystemExit(1)


def _drop_all():
    """把测试库清成空库（含 alembic_version），模拟首次启动前的空库状态。"""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(bind=engine)


def _child_init(barrier, queue):
    """子进程：等待起跑信号后完整执行 init_db()（模拟一个 uvicorn worker 的 lifespan）。"""
    try:
        barrier.wait(timeout=120)
        init_db()
        queue.put((os.getpid(), None))
    except Exception as exc:  # noqa: BLE001
        queue.put((os.getpid(), f"{type(exc).__name__}: {str(exc)[:300]}"))


def _spawn_round():
    """spawn 两个独立进程同时执行 init_db；返回每个子进程的 (exitcode, err) 列表。"""
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    procs = [ctx.Process(target=_child_init, args=(barrier, queue)) for _ in range(2)]
    for p in procs:
        p.start()
    results: dict[int, str | None] = {}
    for _ in range(2):
        pid, err = queue.get(timeout=180)
        results[pid] = err
    for p in procs:
        p.join(timeout=15)
    return [(p.exitcode, results.get(p.pid)) for p in procs]


def _verify_schema_and_seed():
    db = SessionLocal()
    try:
        tables = inspect(db.bind).get_table_names()
        if "feedback" not in tables:
            _step_fail(f"feedback 表未创建（当前表：{sorted(tables)}）")
        admins = db.query(User).filter(User.username == "admin").count()
        if admins != 1:
            _step_fail(f"admin 用户数量异常（期望 1，实际 {admins}）")
    finally:
        db.close()


def run():
    print("=== HYPE-72 真实 PostgreSQL 双进程首次空库 init_db 并发回归 ===", flush=True)
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        _step_fail("DATABASE_URL 必须指向 PostgreSQL 独立测试库（当前非 PG）")
    dbname = os.environ["DATABASE_URL"].rsplit("/", 1)[-1]
    if dbname == "agvpm":
        _step_fail("拒绝在生产库 agvpm 上运行回归（脚本会建表删表）")

    _drop_all()
    _step_ok(f"已将 {dbname} 清成空库（含 alembic_version）")

    for label, outcomes in [
        ("首次空库并发 init_db", _spawn_round()),
        ("重复并发 init_db（再次启动）", _spawn_round()),
    ]:
        for exitcode, err in outcomes:
            if exitcode != 0:
                _step_fail(f"{label}：子进程退出码 {exitcode}，错误={err}")
            if err:
                _step_fail(f"{label}：子进程 init_db 失败：{err}")
        _step_ok(f"{label}：两个进程均成功，无 IntegrityError/无崩溃")

    _verify_schema_and_seed()
    _step_ok("串行化生效：schema 与 seed 恰好一份（feedback 表存在、admin 唯一）")

    print("=== PASS：HYPE-72 真实 PostgreSQL 双进程首次空库 init_db 并发回归全部通过 ===", flush=True)


if __name__ == "__main__":
    try:
        run()
    except SystemExit as exc:
        print(f"=== 回归失败，退出码 {exc.code} ===", flush=True)
        raise
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
