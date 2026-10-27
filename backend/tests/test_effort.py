"""Effort statistics tests: hours derived from reports, not templates."""

from datetime import date, timedelta


def _project_with_reports(client, pm_headers, worker_headers):
    """Project where a worker fills 10 units over 3 person-days."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "耗时统计项目",
        "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-09-30"})
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    assert r.status_code == 200, r.json()
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.json()
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 10})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": ["user-worker-001"]})
    # 找 单车机械与导航调试（per_vehicle, target=10）
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    task = None
    for ph in r.json():
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "单车机械与导航调试":
                    task = t
    # 3 天每天填 3/4/3 → 3 人天完成 10 件
    for i, qty in enumerate([3, 4, 3]):
        client.post("/api/worker/reports", headers=worker_headers, json={
            "task_id": task["id"],
            "work_date": (date(2026, 8, 4) + timedelta(days=i)).isoformat(),
            "completed_quantity": qty,
            "client_uuid": f"effort-{i}",
        })
    return pid, task


def test_scheduler_uses_default_when_no_history(client, pm_headers):
    """Fresh project, no reports → default 4h/unit used, warning raised."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "无历史项目",
        "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-09-30"})
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200
    d = r.json()
    assert "默认 4 小时" in d["warning"] or "暂无耗时统计" in d["warning"]
    assert d["total_hours"] == 10 * 4  # 5 per_vehicle 任务 × 2 台 × 4h
