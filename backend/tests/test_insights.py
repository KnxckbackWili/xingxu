"""Insight tests: overdue, workload, current phase."""

from tests.lifecycle_helpers import versioned
from datetime import date, timedelta


def _project_with_schedule(client, pm_headers):
    """Project with schedule entries; some dates in the past."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "洞察测试项目",
        "status": "planning",
        "start_date": "2026-07-01", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    assert r.status_code == 200, r.json()
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.json()
    # Manual task so schedule starts early
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    manual = None
    for ph in r.json():
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["quantity_type"] == "manual" and not t["target_quantity"]:
                    manual = t
                    break
            if manual: break
        if manual: break
    if manual:
        r = client.put(f"/api/projects/{pid}/tasks/{manual['id']}", headers=pm_headers,
                   json=versioned(manual['id'], {"target_quantity": 4}, 'Task'))
        assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200
    return pid


def test_overdue_empty_when_all_future(client, pm_headers):
    """Schedule entirely in the future → no overdue."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "未来项目",
        "status": "planning",
        "start_date": (date.today() + timedelta(days=30)).isoformat(),
        "end_date": (date.today() + timedelta(days=60)).isoformat(),
    })
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 1})
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.json()
    assert client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()

    r = client.get(f"/api/projects/{pid}/overdue", headers=pm_headers)
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_overdue_detected_for_past_schedule(client, pm_headers):
    """Schedule starting in the past with no completion → overdue entries."""
    pid = _project_with_schedule(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/overdue", headers=pm_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] > 0
    for item in data["items"]:
        assert item["overdue_days"] >= 0
        assert item["work_date"] < date.today().isoformat()
        assert item["phase_name"]
        assert item["phase_relation"] in {"previous", "current", "upcoming"}
        assert item["stage_relevance"]
        assert item["overdue_reason"]


def test_worker_overdue(client, pm_headers, worker_headers):
    pid = _project_with_schedule(client, pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    r = client.get("/api/worker/overdue", headers=worker_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] > 0
    assert data["items"][0]["project_name"] == "洞察测试项目"


def test_dashboard_overdue_aggregation(client, pm_headers, worker_headers):
    """/dashboard/overdue 聚合逾期项目与逾期任务（行动入口数据源）。"""
    pid = _project_with_schedule(client, pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    # 排程已生成且日期已过（未填报）→ 逾期
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    assert len(r.json()) > 0

    r = client.get("/api/dashboard/overdue", headers=pm_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["count"] > 0
    proj = next((p for p in d["projects"] if p["project_id"] == pid), None)
    assert proj is not None
    assert proj["count"] > 0
    assert "task_name" in proj["items"][0] and "overdue_days" in proj["items"][0]


def test_current_phase(client, pm_headers):
    pid = _project_with_schedule(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/current-phase", headers=pm_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["current"] is not None
    assert len(d["chain"]) > 0
    # First phase has no progress yet (nothing completed)
    assert d["chain"][0]["percent"] == 0
    assert d["current"]["name"] == d["chain"][0]["name"]


def test_people_plan_is_limited_to_visible_projects(client, pm_headers, worker_headers):
    pid = _project_with_schedule(client, pm_headers)
    response = client.get("/api/dashboard/people-plan", headers=worker_headers)
    assert response.status_code == 200
    assert all(item["project_id"] != pid for item in response.json()["entries"])

    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    response = client.get("/api/dashboard/people-plan", headers=worker_headers)
    assert response.status_code == 200
    assert any(item["project_id"] == pid for item in response.json()["entries"])


def test_people_plan_entries_carry_task_and_status_fields(client, pm_headers):
    """HYPE-77：条目携带 task_id/status/is_confirmed/completed_quantity，供我的日历展示与跳转。"""
    pid = _project_with_schedule(client, pm_headers)
    r = client.get("/api/dashboard/people-plan", headers=pm_headers)
    assert r.status_code == 200
    entries = [e for e in r.json()["entries"] if e["project_id"] == pid]
    assert entries, "应至少有一条排程条目"
    for e in entries:
        assert e["task_id"]
        assert e["task_name"]
        assert e["unit"]
        assert e["status"] in ("planned", "done")
        assert isinstance(e["is_confirmed"], bool)
        assert e["completed_quantity"] == 0
