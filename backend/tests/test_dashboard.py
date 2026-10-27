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


def test_worker_sees_only_own_projects(client, pm_headers, worker_headers):
    _project_with_data(client, pm_headers)  # no members
    r = client.get("/api/dashboard/overview", headers=worker_headers)
    assert r.status_code == 200
    assert r.json()["stats"]["total_projects"] == 0


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


def test_overview_includes_people_block(client, pm_headers):
    """HYPE-58：overview 返回 people（在职可排程/已分配·未分配/计划工时/利用率/超负荷/角色分布）。"""
    _project_with_data(client, pm_headers)
    response = client.get("/api/dashboard/overview", headers=pm_headers)
    assert response.status_code == 200, response.text
    people = response.json()["people"]
    summary = people["summary"]
    # 关键聚合字段齐备
    assert summary["active_people"] >= 1
    assert "scheduled_people" in summary
    assert "unassigned_people" in summary
    assert summary["unassigned_people"] == summary["active_people"] - summary["scheduled_people"]
    assert summary["planned_hours"] >= 0
    assert "avg_load_percent" in summary
    assert "overloaded_people" in summary
    # 保留角色分布，内部组织分组已退休。
    assert sum(item["count"] for item in people["role_distribution"]) == summary["active_people"]
    assert "group_distribution" not in people
    # 列表只含人员/工时/负荷摘要，不泄露项目名
    for item in people["items"]:
        assert "name" in item and "role" in item
        assert "projects" not in item
        assert "planned_hours" in item and "load_percent" in item
    # 与 people-summary 口径一致
    ps = client.get("/api/dashboard/people-summary", headers=pm_headers).json()
    assert ps["summary"]["active_people"] == summary["active_people"]


def test_overview_people_scoped_to_visible_projects(client, pm_headers, worker_headers):
    """HYPE-58：worker 只见自己参与项目的人员摘要；无关项目成员不进入统计。"""
    _project_with_data(client, pm_headers)  # 无成员，worker 不可见
    response = client.get("/api/dashboard/overview", headers=worker_headers)
    assert response.status_code == 200, response.text
    assert response.json()["stats"]["total_projects"] == 0
    # 不可见项目 → 其成员不进 people 摘要（worker 只看到自己）
    assert response.json()["people"]["summary"]["active_people"] == 1




def test_overview_empty_project_has_empty_units_and_unchanged_zero_progress(client, pm_headers):
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
    assert item["quantities_by_unit"] == []
    assert (item["completed"], item["target"], item["percent"]) == (0, 0, 0)


def test_overview_keeps_original_units_separate_and_counts_equal_work_items(client, pm_headers):
    from datetime import date
    from app.db import SessionLocal
    from app.models import DailyProgress, Module, Phase, Project, Task

    with SessionLocal() as db:
        project = Project(name="工作台混合计量", manager="user-pm-001", status="executing",
                          start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
        db.add(project)
        db.flush()
        phase = Phase(project_id=project.id, name="现场实施")
        preparation = Phase(project_id=project.id, name="项目准备")
        db.add_all([phase, preparation])
        db.flush()
        module = Module(project_id=project.id, phase_id=phase.id, name="执行计量")
        preparation_module = Module(project_id=project.id, phase_id=preparation.id, name="提醒计量")
        db.add_all([module, preparation_module])
        db.flush()
        task_ids = []
        for index, (owner, module_id, unit, target, completed) in enumerate([
            (project.id, module.id, "台", 10, 1),
            (project.id, module.id, " 米 ", 20, 2),
            (project.id, module.id, " ", 10, 1),
            (project.id, preparation_module.id, "提醒单位", 100, 100),
        ]):
            task = Task(project_id=owner, module_id=module_id, name=f"计量任务{index}",
                        quantity_type="fixed", target_quantity=target, unit=unit)
            db.add(task)
            db.flush()
            task_ids.append(task.id)
            db.add(DailyProgress(project_id=owner, task_id=task.id, user_id="user-pm-001",
                                 work_date=date.today(), completed_quantity=completed,
                                 client_uuid=f"overview-unit-{index}"))
        project_id = project.id
        db.commit()

    response = client.get("/api/dashboard/overview", headers=pm_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    item = next(item for item in data["projects"] if item["id"] == project_id)
    assert {row["unit"]: (row["completed"], row["target"]) for row in item["quantities_by_unit"]} == {
        "台": (1, 10), "米": (2, 20), "项": (1, 10),
    }
    assert (item["completed"], item["target"], item["percent"]) == (0, 3, 0)

    # A signed correction affects its real unit; the old numeric contract stays compatible.
    with SessionLocal() as db:
        db.add(DailyProgress(project_id=project_id, task_id=task_ids[1], user_id="user-pm-001",
                             work_date=date.today(), completed_quantity=-0.5,
                             client_uuid="overview-unit-correction", source="pm"))
        db.commit()
    updated = client.get("/api/dashboard/overview", headers=pm_headers).json()["projects"][0]
    assert {row["unit"]: row["completed"] for row in updated["quantities_by_unit"]} == {
        "台": 1, "米": 1.5, "项": 1,
    }
    assert (updated["completed"], updated["target"], updated["percent"]) == (0, 3, 0)
