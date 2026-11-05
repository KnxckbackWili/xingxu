"""Current progress: work-item completion and real vehicle steps, never daily quantities."""
from tests.lifecycle_helpers import versioned
from tests.template_work import default_work


def _setup(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "进度测试项目", "start_date": "2026-08-01", "end_date": "2026-09-30", "new_vehicles": False,
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    # A configured fleet makes the vehicle-step target known; otherwise progress stays unknown (0).
    vehicles = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 1})
    assert vehicles.status_code == 200, vehicles.text
    generated = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"work_item_ids": default_work("mod-01", "mod-04")})
    assert generated.status_code == 200, generated.text
    from tests.lifecycle_helpers import enter_execution
    enter_execution(client, pm_headers, pid)
    return pid


def _complete_phase(pid, phase_name):
    from app.db import SessionLocal
    from app.models import CheckItem, Phase, Task
    with SessionLocal() as db:
        phase = db.query(Phase).filter_by(project_id=pid, name=phase_name).one()
        for task in db.query(Task).filter_by(project_id=pid, phase_id=phase.id):
            for check in db.query(CheckItem).filter_by(task_id=task.id):
                check.is_done = True
            task.manually_completed = True
        db.commit()


def test_progress_without_configured_fleet_is_unknown_not_complete(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={"name": "无车型", "start_date": "2026-08-01", "end_date": "2026-09-30", "new_vehicles": False})
    pid = r.json()["id"]
    data = client.get(f"/api/projects/{pid}/progress", headers=pm_headers).json()
    assert data["progress_known"] is False and data["percent"] == 0


def test_progress_starts_at_zero(client, pm_headers):
    pid = _setup(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/progress", headers=pm_headers)
    assert r.status_code == 200, r.text
    assert r.json()["percent"] == 0


def test_completed_work_items_raise_progress_equally(client, pm_headers):
    pid = _setup(client, pm_headers)
    _complete_phase(pid, "发车前")
    data = client.get(f"/api/projects/{pid}/progress", headers=pm_headers).json()
    assert 0 < data["percent"] < 100
    phases = {row["name"]: row for row in data["phases"]}
    assert phases["发车前"]["percent"] == 100


def test_timeline_returns_series(client, pm_headers):
    pid = _setup(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/progress/timeline", headers=pm_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and rows
    assert {"date", "planned", "actual"} <= set(rows[0])


def test_current_phase_moves_after_earlier_work_completes(client, pm_headers):
    pid = _setup(client, pm_headers)
    first = client.get(f"/api/projects/{pid}/current-phase", headers=pm_headers)
    assert first.status_code == 200, first.text
    assert first.json()["current"]["name"] == "发车前"
    _complete_phase(pid, "发车前")
    moved = client.get(f"/api/projects/{pid}/current-phase", headers=pm_headers).json()
    assert moved["current"]["name"] == "系统部署与联调"
    assert [row["name"] for row in moved["chain"]][:2] == ["发车前", "系统部署与联调"]


def test_project_and_dashboard_overdue_are_document_based(client, pm_headers):
    pid = _setup(client, pm_headers)
    project = client.get(f"/api/projects/{pid}/overdue", headers=pm_headers)
    assert project.status_code == 200, project.text
    assert {"count", "items", "timezone"} <= set(project.json())
    dashboard = client.get("/api/dashboard/overdue", headers=pm_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert {"count", "projects", "this_week_count"} <= set(dashboard.json())


def test_project_members_unchanged_by_progress_reads(client, pm_headers):
    pid = _setup(client, pm_headers)
    before = client.get(f"/api/projects/{pid}", headers=pm_headers).json()["version"]
    client.get(f"/api/projects/{pid}/progress", headers=pm_headers)
    client.get(f"/api/projects/{pid}/current-phase", headers=pm_headers)
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["version"] == before
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"description": "读取后仍可编辑"})).status_code == 200
