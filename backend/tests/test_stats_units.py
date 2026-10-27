"""Physical units stay separate in the real statistics endpoints."""
from datetime import date
from uuid import uuid4


def _add_project(db, name, task_units, reports):
    from app.models import Project, Phase, Module, Task, DailyProgress
    project = Project(name=name, manager="user-pm-001", members=["user-worker-001", "unit-other"],
                      start_date=date(2026, 1, 1), end_date=date(2027, 1, 1), status="executing")
    db.add(project); db.flush()
    phase = Phase(project_id=project.id, name="现场实施")
    db.add(phase); db.flush()
    module = Module(project_id=project.id, phase_id=phase.id, name="统计计量")
    db.add(module); db.flush()
    tasks = []
    for unit in task_units:
        task = Task(project_id=project.id, module_id=module.id, name="同名工作", quantity_type="fixed", target_quantity=10, unit=unit)
        db.add(task); db.flush(); tasks.append(task)
    for index, user_id, quantity in reports:
        db.add(DailyProgress(project_id=project.id, task_id=tasks[index].id, user_id=user_id,
                             work_date=date.today(), completed_quantity=quantity, client_uuid=str(uuid4())))
    db.flush()
    return project.id, [task.id for task in tasks]


def _mixed_fixture():
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        name = db.get(User, "user-worker-001").display_name
        db.add(User(id="unit-other", username="unit-other", password_hash="unused", display_name=name, role="worker"))
        pid, tasks = _add_project(db, "多单位项目", ["台", " 米 ", "项"], [(0, "user-worker-001", 1), (1, "user-worker-001", 2), (2, "unit-other", 1)])
        _add_project(db, "另一个米制项目", ["米"], [(0, "unit-other", 4)])
        db.commit()
    return pid, tasks


def test_summary_weekly_people_and_projects_keep_units_and_same_named_users(client, pm_headers):
    pid, _ = _mixed_fixture()
    result = client.get("/api/dashboard/stats", headers=pm_headers)
    assert result.status_code == 200, result.text
    stats = result.json()
    summary = {row["unit"]: row for row in stats["summary"]["quantities_by_unit"]}
    assert {unit: row["completed"] for unit, row in summary.items()} == {"台": 1, "米": 6, "项": 1}
    assert summary["米"]["reports"] == 2
    assert summary["米"]["hours_per_unit"] == 2.67
    assert stats["summary"]["avg_hours_per_unit"] is None
    assert stats["summary"]["total_completed"] == 8  # legacy numeric field retained
    people = {row["user_id"]: row for row in stats["workload"]}
    assert len(people) == 2 and len({row["name"] for row in people.values()}) == 1
    worker = {row["unit"]: (row["quantity"], row["reports"]) for row in people["user-worker-001"]["quantities_by_unit"]}
    assert worker == {"台": (1, 1), "米": (2, 1)}
    assert people["user-worker-001"]["quantity"] == 3
    assert people["user-worker-001"]["reports"] == 2
    effort = {row["unit"]: row for row in stats["effort"]}
    assert len(effort) == 3
    assert effort["米"]["project_count"] == 2
    assert effort["台"]["hours_per_unit"] == 8
    project = next(row for row in stats["projects"] if row["id"] == pid)
    assert {row["unit"]: (row["completed"], row["target"]) for row in project["quantities_by_unit"]} == {"台": (1, 10), "米": (2, 10), "项": (1, 10)}
    assert project["percent"] == 13.3  # original target-weighted percentage
    metrics = client.get("/api/dashboard/metrics", headers=pm_headers)
    assert metrics.status_code == 200, metrics.text
    week = metrics.json()["weekly"][-1]
    assert {row["unit"]: row["quantity"] for row in week["quantities_by_unit"]} == {"台": 1, "米": 6, "项": 1}
    assert week["quantity"] == 8


def test_negative_correction_only_changes_its_unit_and_report_samples(client, pm_headers):
    from app.db import SessionLocal
    from app.models import DailyProgress
    pid, tasks = _mixed_fixture()
    with SessionLocal() as db:
        db.add(DailyProgress(project_id=pid, task_id=tasks[1], user_id="user-worker-001", work_date=date.today(),
                             completed_quantity=-0.5, client_uuid="negative-unit-correction", source="pm"))
        db.commit()
    stats = client.get("/api/dashboard/stats", headers=pm_headers).json()
    summary = {row["unit"]: row for row in stats["summary"]["quantities_by_unit"]}
    assert {unit: row["completed"] for unit, row in summary.items()} == {"台": 1, "米": 5.5, "项": 1}
    assert summary["米"]["reports"] == 3
    worker = next(row for row in stats["workload"] if row["user_id"] == "user-worker-001")
    assert next(row for row in worker["quantities_by_unit"] if row["unit"] == "米") == {"unit": "米", "quantity": 1.5, "reports": 2}
    week = client.get("/api/dashboard/metrics", headers=pm_headers).json()["weekly"][-1]
    assert {row["unit"]: row["quantity"] for row in week["quantities_by_unit"]} == {"台": 1, "米": 5.5, "项": 1}


def test_single_unit_legacy_average_and_zero_net_samples(client, pm_headers):
    from app.db import SessionLocal
    from app.models import DailyProgress
    with SessionLocal() as db:
        pid, tasks = _add_project(db, "单单位", [" "], [(0, "user-worker-001", 3)])
        db.commit()
    stats = client.get("/api/dashboard/stats", headers=pm_headers).json()
    assert stats["summary"]["avg_hours_per_unit"] == 2.67
    assert stats["summary"]["quantities_by_unit"] == [{"unit": "项", "completed": 3, "reports": 1, "hours_per_unit": 2.67}]
    with SessionLocal() as db:
        db.add(DailyProgress(project_id=pid, task_id=tasks[0], user_id="user-worker-001", work_date=date.today(),
                             completed_quantity=-3, client_uuid="zero-net-correction", source="pm"))
        db.commit()
    stats = client.get("/api/dashboard/stats", headers=pm_headers).json()
    assert stats["summary"]["quantities_by_unit"] == [{"unit": "项", "completed": 0, "reports": 2, "hours_per_unit": None}]
    assert stats["summary"]["avg_hours_per_unit"] is None
    assert stats["summary"]["total_person_days"] == 0  # retain legacy positive-effort-only count
    assert stats["effort"] == []
