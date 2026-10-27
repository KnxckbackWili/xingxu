"""HYPE-65 真实 PostgreSQL 多 worker 首次启动并发 seed 回归（独立库 agvpm_pgtest，不碰生产 agvpm）。

背景：生产以 `uvicorn --workers 2` 运行，每个 worker 的 lifespan 都会调用 init_db() → seed_vehicle_types()。
旧实现“查询已有名称 → 逐项 INSERT”在空字典并发首次启动时，两个 worker 可能同时插入同名车型，
触发 vehicle_types.name 唯一键冲突，导致其中一个 worker 启动失败。
本次修复改为 INSERT ... ON CONFLICT DO NOTHING（SQLite ≥3.24 与 PostgreSQL 均支持）。

运行方式（本机 / 容器内均可，先建独立测试库）：
    psql -U <user> -h 127.0.0.1 -d postgres -c "DROP DATABASE IF EXISTS agvpm_pgtest"
    psql -U <user> -h 127.0.0.1 -d postgres -c "CREATE DATABASE agvpm_pgtest"
    cd backend && SEED_DEMO_USERS=1 DATABASE_URL="postgresql+psycopg2://<user>@127.0.0.1:5432/agvpm_pgtest" \\
      python tests/pg_seed_vehicle_types_concurrency.py
    psql -U <user> -h 127.0.0.1 -d postgres -c "DROP DATABASE IF EXISTS agvpm_pgtest"

验证内容：
  1. 旧 seed 实现（查询已有 → 逐项 INSERT）在“会话 A 独占唯一键、会话 B 随后插入”下必然触发
     name 唯一键冲突——证明该竞态真实存在、修复必要。
  2. 新 seed 实现（ON CONFLICT DO NOTHING）在两个并发会话同时面对空字典时均成功，恰好落一份。
  3. 重复并发 seed（再次启动 / 重复启动）保持幂等，不报错、不覆盖管理员数据。
"""

import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import VehicleType  # noqa: E402
from app.seed.seed_data import PRESET_VEHICLE_TYPES, seed_vehicle_types  # noqa: E402

PASS = "✅"
FAIL = "❌"


def _step_ok(msg: str):
    print(f"{PASS} {msg}")


def _step_fail(msg: str):
    print(f"{FAIL} {msg}")
    raise SystemExit(1)


def _clear_vehicle_types():
    db = SessionLocal()
    try:
        db.query(VehicleType).delete()
        db.commit()
    finally:
        db.close()


def _old_impl_fails_on_pg() -> str:
    """复现旧 seed（查询已有 → 逐项 INSERT）在并发下的唯一键冲突（确定性构造）。"""
    _clear_vehicle_types()

    # 会话 A：先插入但不提交，name 唯一键被 A 事务占用
    a = SessionLocal()
    for i, name in enumerate(PRESET_VEHICLE_TYPES, start=1):
        a.add(VehicleType(name=name, is_enabled=True, sort_order=i))
    a.flush()

    # 会话 B：同样插入 → flush 处阻塞等待 A；A 提交后触发唯一键冲突
    b = SessionLocal()
    errors: list[Exception] = []

    def _b():
        try:
            for i, name in enumerate(PRESET_VEHICLE_TYPES, start=1):
                b.add(VehicleType(name=name, is_enabled=True, sort_order=i))
            b.flush()
            b.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            b.close()

    t = threading.Thread(target=_b)
    t.start()
    time.sleep(1)  # 让 B 进入 flush 阻塞
    try:
        a.commit()
    finally:
        a.close()
    t.join(timeout=10)

    if not errors:
        return ""
    return f"{type(errors[0]).__name__}: {str(errors[0])[:180]}"


def _concurrent_seed(clean_first: bool):
    """两个并发会话同时 seed（模拟两个 worker 首次/重复启动）。"""
    if clean_first:
        _clear_vehicle_types()

    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def _seed():
        s = SessionLocal()
        try:
            barrier.wait(timeout=10)
            seed_vehicle_types(s)
            s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=_seed) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    if errors:
        _step_fail(f"并发 seed 失败：{[str(e) for e in errors]}")
    db = SessionLocal()
    try:
        rows = db.query(VehicleType).order_by(VehicleType.sort_order).all()
        names = [t.name for t in rows]
        if names != PRESET_VEHICLE_TYPES or len(rows) != len(PRESET_VEHICLE_TYPES):
            _step_fail(f"并发 seed 结果不完整：{len(rows)} 行，{names}")
    finally:
        db.close()


def run():
    print("=== HYPE-65 真实 PostgreSQL 并发 seed 回归（多 worker 首次启动） ===")
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        _step_fail("DATABASE_URL 必须指向 PostgreSQL 独立测试库（当前非 PG）")
    dbname = os.environ["DATABASE_URL"].rsplit("/", 1)[-1]
    if dbname == "agvpm":
        _step_fail("拒绝在生产库 agvpm 上运行回归（脚本会建表删表）")

    init_db()  # create_all + migrate + seed（先把 schema 建好）

    # 1) 旧实现竞态必失败（证明修复必要）
    err = _old_impl_fails_on_pg()
    if not err:
        _step_fail("旧 seed 实现未按预期在并发下触发唯一键冲突（无法证明修复必要性）")
    _step_ok(f"旧 seed（查询→逐项 INSERT）在双会话并发下触发唯一键冲突：{err}")

    # 2) 新实现并发安全：两个会话同时面对空字典
    _concurrent_seed(clean_first=True)
    _step_ok("两个并发会话 seed（空字典起点）均成功，字典恰好一份（7 项）")

    # 3) 幂等重入：重复/并发再次启动
    _concurrent_seed(clean_first=False)
    _step_ok("重复并发 seed（再次启动）保持幂等，仍为一份 7 项")

    print("=== PASS：HYPE-65 真实 PostgreSQL 并发 seed 回归全部通过 ===")


if __name__ == "__main__":
    try:
        run()
    except SystemExit as exc:
        print(f"=== 回归失败，退出码 {exc.code} ===")
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
