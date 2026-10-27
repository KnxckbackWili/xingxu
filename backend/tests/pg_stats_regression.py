"""T018 真实 PostgreSQL 回归脚本（独立库 agvpm_pgtest，不碰生产 agvpm）。

运行方式（容器内）：
    docker exec agv-pm-8002 sh -c '
      psql -U agv -h 127.0.0.1 -d postgres -c "DROP DATABASE IF EXISTS agvpm_pgtest"
      psql -U agv -h 127.0.0.1 -d postgres -c "CREATE DATABASE agvpm_pgtest"
      cd /app && DATABASE_URL="postgresql+psycopg2://agv:agv@127.0.0.1:5432/agvpm_pgtest" \\
        python tests/pg_stats_regression.py
      psql -U agv -h 127.0.0.1 -d postgres -c "DROP DATABASE IF EXISTS agvpm_pgtest"'

验证内容：
  1. /api/dashboard/stats 在真实 PostgreSQL 下 200，且 workload 含填报人 display_name。
  2. 旧 SQL（只 group_by DailyProgress.user_id 却 select User.display_name）在 PG 下
     必然抛 `must appear in the GROUP BY clause` —— 证明该 bug 是 PG 专属、回归测试
     必须跑真实 PG 才能暴露。
"""

import os
import sys
import traceback

import psycopg2
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine  # noqa: E402

PASS = "✅"
FAIL = "❌"


def _step_ok(msg: str):
    print(f"{PASS} {msg}")


def _step_fail(msg: str):
    print(f"{FAIL} {msg}")
    raise SystemExit(1)


def _old_sql_fails_on_pg() -> str:
    """复现旧 SQL（select u.display_name + group by d.user_id）在 PG 下的报错原文。"""
    url = os.environ["DATABASE_URL"]
    # postgresql+psycopg2://agv:agv@127.0.0.1:5432/agvpm_pgtest
    dsn = url.replace("postgresql+psycopg2://", "").replace("postgresql://", "")
    user, rest = dsn.split(":", 1)
    password, host_port_db = rest.split("@", 1)
    host_port, dbname = host_port_db.rsplit("/", 1)
    host, port = host_port.split(":", 1)
    conn = psycopg2.connect(user=user, password=password, host=host, port=port, dbname=dbname)
    try:
        cur = conn.cursor()
        # 镜像 dashboard.py workload 查询：select 了 users.display_name，但只按 user_id 分组
        cur.execute("""
            SELECT u.display_name, SUM(d.completed_quantity), COUNT(d.id)
            FROM daily_progress d JOIN users u ON u.id = d.user_id
            GROUP BY d.user_id
        """)
        cur.fetchall()
        return ""
    except psycopg2.errors.GroupingError as exc:
        return str(exc).splitlines()[0]
    finally:
        conn.close()


def _make_app():
    from app.main import app
    return app


def run():
    print("=== T018 真实 PostgreSQL 回归：/api/dashboard/stats ===")
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        _step_fail("DATABASE_URL 必须指向 PostgreSQL 独立测试库（当前非 PG）")
    dbname = os.environ["DATABASE_URL"].rsplit("/", 1)[-1]
    if dbname == "agvpm":
        _step_fail("拒绝在生产库 agvpm 上运行回归（脚本会建表删表）")

    from fastapi.testclient import TestClient

    app = _make_app()
    # ---- 建立项目 + 任务 + 填报，制造 workload 数据 ----
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "pm", "password": "pm123"})
        if r.status_code != 200:
            _step_fail(f"PM 登录失败：{r.status_code} {r.text}")
        pm_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.post("/api/auth/login", json={"username": "worker1", "password": "worker123"})
        if r.status_code != 200:
            _step_fail(f"worker 登录失败：{r.status_code} {r.text}")
        worker_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = client.post("/api/projects", headers=pm_headers, json={
            "name": "T018真实PG回归", "start_date": "2026-08-01", "new_vehicles": False,
            "end_date": "2026-09-30",
        })
        if r.status_code != 200:
            _step_fail(f"建项目失败：{r.status_code} {r.text}")
        pid = r.json()["id"]
        client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
        client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
        client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
            "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
        r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                        json={"module_ids": ["mod-03"]})
        if r.status_code != 200:
            _step_fail(f"生成任务失败：{r.status_code} {r.text}")
        client.put(f"/api/projects/{pid}", headers=pm_headers,
                   json={"members": ["user-worker-001"]})
        tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
        task = None
        for ph in tree:
            for m in ph["modules"]:
                for t in m["tasks"]:
                    task = t
                    break
                if task:
                    break
            if task:
                break
        if not task:
            _step_fail("应生成任务，但树中未找到")
        r = client.post("/api/worker/reports", headers=worker_headers, json={
            "task_id": task["id"], "work_date": "2026-08-06",
            "completed_quantity": 1, "client_uuid": "t018-pg-0001"})
        if r.status_code != 200:
            _step_fail(f"填报失败：{r.status_code} {r.text}")

        # ---- 1) 真实 PG 下 stats 端点 200 + workload 含姓名 ----
        r = client.get("/api/dashboard/stats", headers=pm_headers)
        if r.status_code != 200:
            _step_fail(f"/api/dashboard/stats 在真实 PG 下 {r.status_code}：{r.text}")
        workload = r.json().get("workload", [])
        names = [w["name"] for w in workload]
        if "现场工程师A" not in names:
            _step_fail(f"workload 应含填报人姓名，实际：{names[:5]}")
        _step_ok(f"/api/dashboard/stats 真实 PG 200，workload={names[:3]}")

    # ---- 2) 旧 SQL 在 PG 下必炸（bug 是 PG 专属的证明） ----
    err = _old_sql_fails_on_pg()
    if not err or "GROUP BY" not in err:
        _step_fail(f"旧 SQL 未按预期在 PG 报 GROUP BY 错：{err or '无报错'}")
    _step_ok(f"旧 SQL（select display_name 仅按 user_id 分组）在真实 PG 下报错：{err}")

    print("=== PASS：T018 真实 PostgreSQL 回归全部通过 ===")


if __name__ == "__main__":
    try:
        run()
    except SystemExit as exc:
        print(f"=== 回归失败，退出码 {exc.code} ===")
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
