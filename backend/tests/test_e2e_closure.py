"""P1-验收：端到端闭环（创建→排程→填报→报告）。

用演示数据走完 AGV 项目核心主流程，验证各环节接口联动：
建档(draft) → 明确准备中/计划中 → 生成任务 → 下达(ready) → 执行(executing) →
现场按排程填报 → 自动生成周报（含真实进度数据）。

真实业务数据不可由程序伪造：本用例使用演示项目与演示账号（seed demo users），
人工输入项（客户名称/现场信息/验收结论）在用例内以占位演示值提供，
交付验收清单在最终报告中单列。
"""

import uuid


def _create_project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "端到端闭环演示项目",
        "start_date": "2026-08-10",
        "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.json()
    return r.json()["id"]


def _add_vehicle(client, pm_headers, pid):
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                    json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    assert r.status_code == 200, r.json()


def _add_worker(client, pm_headers, worker_headers, pid):
    r = client.get("/api/auth/me", headers=worker_headers)
    wid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    members = list(r.json()["members"])
    if wid not in members:
        members.append(wid)
    r = client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": members})
    assert r.status_code == 200, r.json()


def _fill_all(client, worker_headers, pid, ratio):
    """按排程条目逐条填报（幂等 client_uuid），返回填报条数。"""
    r = client.get(f"/api/projects/{pid}/schedule", headers=worker_headers)
    assert r.status_code == 200, r.json()
    entries = r.json()
    submitted = 0
    for i, e in enumerate(entries):
        qty = (e.get("planned_quantity") or 0) * ratio
        r = client.post("/api/worker/reports", headers=worker_headers, json={
            "task_id": e["task_id"],
            "schedule_entry_id": e["id"],
            "work_date": e["work_date"],
            "completed_quantity": qty,
            "client_uuid": f"e2e-closure-{pid[:8]}-{i}-{uuid.uuid4().hex[:6]}",
        })
        assert r.status_code == 200, r.json()
        submitted += 1
    return submitted


def test_end_to_end_closure(client, pm_headers, worker_headers):
    # 1. 建档
    pid = _create_project(client, pm_headers)
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    assert r.status_code == 200 and r.json()["status"] == "draft"
    for stage in ("preparing", "planning"):
        changed = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": stage})
        assert changed.status_code == 200, changed.text

    # 2. 车型 → 任务生成
    _add_vehicle(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.json()

    # 3. 排程生成 + 确认 → ready
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert r.status_code == 200, r.json()
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "ready"

    # 4. 进入执行
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.json()

    # 5. 现场填报（worker 50%）
    _add_worker(client, pm_headers, worker_headers, pid)
    submitted = _fill_all(client, worker_headers, pid, 0.5)
    assert submitted > 0, "排程为空，无法填报"

    # 6. 自动生成周报：报告须包含该项目、周期结构与填报落库后的累计进度
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers, params={"period": "week"})
    assert r.status_code == 200, r.json()
    report = r.json()
    assert report["project"]["id"] == pid
    assert report["period"] == "week"
    assert report["period_label"] and report["generated_at"]
    # 累计进度来自全部 daily_progress（跨周期累计），填报 50% 后必大于 0
    progress = report["progress"]
    assert progress["target"] > 0, "排程目标量缺失"
    assert progress["completed"] > 0, "填报未落入累计进度"
    assert 0 <= progress["percent"] <= 100
    # summary 结构完整
    for key in ("completed_quantity", "report_count", "person_count",
                "issues_opened", "issues_resolved", "open_issues", "next_period_tasks"):
        assert key in report["summary"], f"summary 缺少 {key}"

    # 7. 填报台账可回溯
    r = client.get("/api/worker/records", headers=worker_headers)
    assert r.status_code == 200, r.json()
    assert len(r.json()) >= submitted


def test_report_rejects_unknown_project(client, admin_headers):
    r = client.get("/api/projects/not-exist/report", headers=admin_headers)
    assert r.status_code == 404
