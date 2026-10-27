"""Dashboard overview tests."""
from tests.lifecycle_helpers import versioned


def _project_with_data(client, pm_headers):
    """Project with tasks, progress, and an open issue."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "看板测试项目A",
        "start_date": "2026-08-01", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    from tests.lifecycle_helpers import enter_execution
    enter_execution(client, pm_headers, pid)
    response = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    assert response.status_code == 200, response.json()
    response = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    assert response.status_code == 200, response.json()
    response = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "安全问题", "severity": "critical"})
    assert response.status_code == 200, response.json()
    return pid


def test_overview_stats(client, pm_headers):
    pid = _project_with_data(client, pm_headers)
    r = client.get("/api/dashboard/overview", headers=pm_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["stats"]["total_projects"] == 1
    assert d["stats"]["active_projects"] == 1
    assert d["stats"]["open_issues"] == 1
    assert d["stats"]["critical_issues"] == 1
    # Project in list
    assert len(d["projects"]) == 1
    p = d["projects"][0]
    assert p["id"] == pid
    assert p["percent"] == 0
    assert p["critical_issues"] == 1


def test_overview_reflects_progress(client, pm_headers, worker_headers):
    pid = _project_with_data(client, pm_headers)
    # Worker completes some work
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree = r.json()
    task = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "单车机械与导航调试":
                    task = t
    client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": task["id"], "work_date": "2026-08-06",
        "completed_quantity": 1, "client_uuid": "dash-0001"})

    from tests.test_project_events import unit
    from tests.test_vehicle_progress import write
    vid=client.get(f"/api/projects/{pid}/vehicles",headers=pm_headers).json()[0]['id']
    real=unit(client,pm_headers,pid,vid,'真实AGV-01')
    assert write(client,pm_headers,pid,[real]).status_code==200
    r = client.get("/api/dashboard/overview", headers=pm_headers)
    p = r.json()["projects"][0]
    assert p["completed"] == 1
    assert p["percent"] > 0


def test_field_worker_has_no_management_workbench(client, pm_headers, worker_headers):
    _project_with_data(client, pm_headers)  # no members
    r = client.get("/api/dashboard/overview", headers=worker_headers)
    assert r.status_code == 403, r.text


def test_scoped_issues_preserve_creation_time_and_date_trend(client, pm_headers):
    pid = _project_with_data(client, pm_headers)
    issue = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()[0]
    response = client.get("/api/dashboard/issues", headers=pm_headers)
    assert response.status_code == 200
    item = next(row for row in response.json()["items"] if row["id"] == issue["id"])
    assert item["created_at"] == issue["created_at"]
    assert "T" in item["created_at"]
    assert len(response.json()["trend"]) == 7
    assert response.json()["trend"][-1] == 1


def test_overview_handles_one_hundred_projects(client, pm_headers):
    from datetime import date
    from app.db import SessionLocal
    from app.models import Project

    db = SessionLocal()
    try:
        for index in range(100):
            db.add(Project(
                name=f"容量测试项目 {index + 1:03d}",
                manager="user-pm-001",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 12, 31),
                status="preparing",
                members=[],
            ))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/dashboard/overview", headers=pm_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["stats"]["total_projects"] == 100
    assert data["stats"]["active_projects"] == 100
    assert len(data["projects"]) == 100


def test_overview_empty_project_has_unknown_zero_progress(client, pm_headers):
    from datetime import date
    from app.db import SessionLocal
    from app.models import Project

    with SessionLocal() as db:
        project = Project(name="工作台空计量", manager="user-pm-001", status="preparing",
                          start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
        db.add(project)
        db.commit()
        project_id = project.id
    response = client.get("/api/dashboard/overview", headers=pm_headers)
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["projects"] if item["id"] == project_id)
    assert "quantities_by_unit" not in item
    assert item["percent"] == 0 and item["completed"] == 0