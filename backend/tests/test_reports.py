"""Report generation: real field actuals, document submissions and vehicle-step progress."""
from tests.lifecycle_helpers import versioned


def _project_with_work(client, pm_headers, worker_headers):
    """On-site project where the worker records one work item complete this week, plus an open issue."""
    from app.db import SessionLocal
    from app.models import CheckItem, Phase, Task
    from tests.lifecycle_helpers import enter_execution
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "报告测试项目", "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-12-31",
    })
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    assert client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2}).status_code == 200
    assert client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-01"]}).status_code == 200
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]})).status_code == 200
    enter_execution(client, pm_headers, pid)
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=pid, name="场地勘测").one()
        checks = [(c.id, c.version or 0) for c in db.query(CheckItem).filter_by(task_id=task.id)]
        tid = task.id
    for cid, version in checks:
        assert client.put(f"/api/projects/{pid}/check-items/{cid}", headers=worker_headers,
                          json={"is_done": True, "version": version}).status_code == 200
    with SessionLocal() as db:
        version = db.get(Task, tid).version or 0
    done = client.put(f"/api/projects/{pid}/work-items/{tid}/completion", headers=worker_headers,
                      json={"version": version, "is_completed": True, "reason": "现场勘测完成"})
    assert done.status_code == 200, done.text
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={"title": "联调异常", "severity": "high"})
    assert r.status_code == 200, r.json()
    return pid


def test_weekly_report_shape(client, pm_headers, worker_headers):
    pid = _project_with_work(client, pm_headers, worker_headers)
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers, params={"period": "week"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["project"]["name"] == "报告测试项目"
    assert d["period"] == "week"
    # Real field actuals: the worker's completion (and the checks it required).
    assert d["summary"]["completed_work"] == 1
    assert d["summary"]["actual_records"] >= 1
    assert any(row["kind"] == "work" and row["target_name"] == "场地勘测" and row["is_done"] for row in d["completed_items"])
    assert any(person["name"] == "现场工程师A" for person in d["per_person"])
    # Open issue and this week's kickoff document submissions are reported.
    assert d["summary"]["open_issues"] == 1 and len(d["open_issues"]) == 1
    assert d["summary"]["documents_submitted"] >= 1
    assert d["document_summary"]["submitted"] == d["summary"]["documents_submitted"]
    # Vehicle-step progress, not quantities: 2 vehicles × default steps, none done yet.
    assert d["progress"]["target"] > 0 and d["progress"]["completed"] == 0


def test_weekly_report_empty_period(client, pm_headers):
    """A week with no work still generates a valid report."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "空报告项目", "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-09-30",
    })
    pid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers, params={"period": "week", "ref_date": "2026-08-06"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["summary"]["actual_records"] == 0
    assert d["summary"]["completed_work"] == 0
    assert d["completed_items"] == []


def test_monthly_report_period(client, pm_headers, worker_headers):
    pid = _project_with_work(client, pm_headers, worker_headers)
    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers, params={"period": "month"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["period"] == "month"
    assert d["summary"]["completed_work"] == 1
