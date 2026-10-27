"""P1-验收：v3 端到端闭环（建档→筹备资料→进场→现场实际→签单→验收→完成→归档→周报）。

全程使用真实接口与门禁：人工推进项目状态，现场登记不会自动改变状态；
人工输入项（客户名称/验收结论等）在用例内以占位演示值提供。
"""

from tests.lifecycle_helpers import versioned, enter_execution, complete_vehicle_progress, register_kickoff


def _status(client, headers, pid):
    return client.get(f"/api/projects/{pid}", headers=headers).json()["status"]


def _advance(client, headers, pid, target, **extra):
    response = client.post(f"/api/projects/{pid}/status", headers=headers, json={"status": target, **extra})
    assert response.status_code == 200, response.text
    assert _status(client, headers, pid) == target


def test_end_to_end_closure(client, pm_headers, worker_headers):
    from app.db import SessionLocal
    from app.models import CheckItem, Task
    from tests.document_helpers import complete_documents
    # 1. 建档：新项目只能从筹备开始
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "端到端闭环演示项目", "start_date": "2026-08-10", "end_date": "2026-09-30", "new_vehicles": False})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert _status(client, pm_headers, pid) == "preparing"
    assert client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
        json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2}).status_code == 200
    assert client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-01"]}).status_code == 200
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    members = client.get(f"/api/projects/{pid}", headers=pm_headers).json()["members"]
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": [*members, wid]})).status_code == 200

    # 2. 筹备资料 → 待进场 → 风险批准 → 现场实施
    enter_execution(client, pm_headers, pid)
    assert _status(client, pm_headers, pid) == "executing"

    # 3. 现场实际：工程师逐车登记环节、完成检查与工作；登记不会自动推进项目状态
    complete_vehicle_progress(client, pm_headers, pid)
    with SessionLocal() as db:
        tasks = [t.id for t in db.query(Task).filter_by(project_id=pid) if t.quantity_type != "per_vehicle"]
        checks = [(c.id, c.version or 0) for c in db.query(CheckItem).filter(CheckItem.task_id.in_(tasks))]
    for cid, version in checks:
        r = client.put(f"/api/projects/{pid}/check-items/{cid}", headers=worker_headers, json={"is_done": True, "version": version})
        assert r.status_code == 200, r.text
    for tid in tasks:
        with SessionLocal() as db:
            version = db.get(Task, tid).version or 0
        r = client.put(f"/api/projects/{pid}/work-items/{tid}/completion", headers=worker_headers,
                       json={"version": version, "is_completed": True, "reason": "现场完成并自检"})
        assert r.status_code == 200, r.text
    progress = client.get(f"/api/projects/{pid}/progress", headers=pm_headers).json()
    assert progress["percent"] == 100
    assert _status(client, pm_headers, pid) == "executing"

    # 4. 签单资料与全周期资料齐备 → 验收中 → 客户签字 → 已完成 → 复盘归档
    register_kickoff(client, pm_headers, pid)
    complete_documents(client, pm_headers, pid)
    _advance(client, pm_headers, pid, "acceptance")
    r = client.post(f"/api/projects/{pid}/acceptance", headers=pm_headers, json={
        "accepted_by_name": "客户验收代表", "accepted_at": "2026-09-30", "conclusion": "accepted", "notes": "现场验收通过"})
    assert r.status_code == 200, r.text
    complete_documents(client, pm_headers, pid)
    _advance(client, pm_headers, pid, "completed")
    _advance(client, pm_headers, pid, "archived", retrospective="项目顺利收官，客户已验收")

    # 5. 周报：包含本周资料提交与真实现场实际，结构完整
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers, params={"period": "week"})
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["project"]["id"] == pid and report["period"] == "week"
    for key in ("actual_records", "completed_work", "vehicle_completions", "documents_submitted", "open_issues"):
        assert key in report["summary"], key
    assert report["summary"]["documents_submitted"] > 0
    assert report["summary"]["completed_work"] == len(tasks)


def test_report_rejects_unknown_project(client, admin_headers):
    r = client.get("/api/projects/not-exist/report", headers=admin_headers)
    assert r.status_code == 404
