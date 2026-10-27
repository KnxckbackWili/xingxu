"""Report generation tests."""
from tests.lifecycle_helpers import versioned


def _project_with_work(client, pm_headers, worker_headers):
    """Project with completed work + issue + schedule."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "报告测试项目",
        "start_date": "2026-08-01", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    from tests.lifecycle_helpers import enter_execution
    enter_execution(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.json()
    r = client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    assert r.status_code == 200, r.json()
    # Worker completes 1 unit of 单车机械与导航调试 on 2026-08-05
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    task = None
    for ph in r.json():
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "单车机械与导航调试":
                    task = t
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": task["id"], "work_date": "2026-08-05",
        "completed_quantity": 1, "client_uuid": "report-0001"})
    assert r.status_code == 200, r.json()
    # Issue
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "联调异常", "severity": "high"})
    assert r.status_code == 200, r.json()
    return pid


def test_weekly_report_shape(client, pm_headers, worker_headers):
    pid = _project_with_work(client, pm_headers, worker_headers)
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers,
                   params={"period": "week", "ref_date": "2026-08-06"})
    assert r.status_code == 200
    d = r.json()
    assert d["project"]["name"] == "报告测试项目"
    assert d["period"] == "week"
    assert d["period_label"].startswith("2026-08-03")  # Monday of that week
    # Completed work captured
    assert d["summary"]["completed_quantity"] == 1
    assert d["summary"]["report_count"] == 1
    assert len(d["completed_items"]) == 1
    assert d["completed_items"][0]["task"] == "单车机械与导航调试"
    # Open issue captured
    assert d["summary"]["open_issues"] == 1
    assert len(d["open_issues"]) == 1
    # Person summary
    assert d["per_person"][0]["name"] == "现场工程师A"
    assert d["per_person"][0]["quantity"] == 1
    # Progress present: 1 of 10 units done = 10%
    assert d["progress"]["percent"] == 10.0
    assert d["progress"]["target"] == 10
    assert d["progress"]["completed"] == 1


def test_weekly_report_empty_period(client, pm_headers):
    """A week with no work still generates a valid report."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "空报告项目",
        "start_date": "2026-08-01", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    pid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers,
                   params={"period": "week", "ref_date": "2026-08-06"})
    assert r.status_code == 200
    d = r.json()
    assert d["summary"]["completed_quantity"] == 0
    assert d["summary"]["report_count"] == 0
    assert isinstance(d["next_plan"], list)


def test_monthly_report_period(client, pm_headers, worker_headers):
    pid = _project_with_work(client, pm_headers, worker_headers)
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers,
                   params={"period": "month", "ref_date": "2026-08-20"})
    assert r.status_code == 200
    d = r.json()
    assert d["period"] == "month"
    assert d["period_label"] == "2026-08-01 ~ 2026-08-31"
    assert d["summary"]["completed_quantity"] == 1
