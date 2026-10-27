"""Portable planning preferences must survive reuse without execution authority."""

from copy import deepcopy
from datetime import date
import json

import pytest

from app.db import SessionLocal
from app.models import (
    ChangeLog, DailyProgress, Module, Phase, Project, ProjectSchedulePolicy, ScheduleEntry, Task,
    TaskDurationOverride, User,
)


def source_project(client, headers, *, active=True, baseline_unit="台"):
    payload = {
        "type": "agvpm-project",
        "project": {"name": "Policy source", "start_date": "2026-11-02",
                    "end_date": "2026-12-31", "status": "planning", "rest_mode": "none"},
        "modules": [{"phase_name": "现场实施", "name": "装调", "tasks": [
            {"source_id": "fixture-task", "name": "Policy task", "quantity_type": "manual",
             "target_quantity": 10, "unit": "台", "standard_hours": 4},
        ]}],
    }
    response = client.post("/api/projects/import/json", headers=headers, json=payload)
    assert response.status_code == 200, response.json()
    project_id = response.json()["id"]
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=project_id).one()
        task_id = task.id
        author = db.query(User).filter_by(username="pm").one().id
        db.add(ProjectSchedulePolicy(project_id=project_id, duration_scale=.5, version=7, updated_by=author))
        db.add(TaskDurationOverride(task_id=task_id, project_id=project_id, workdays=2,
                                   baseline_quantity=10, baseline_unit=baseline_unit,
                                   is_active=active, version=8, updated_by=author,
                                   recovered_from_log_id="source-history"))
        for day in (2, 3):
            db.add(ScheduleEntry(project_id=project_id, task_id=task_id,
                                 work_date=date(2026, 11, day), planned_quantity=5))
        db.commit()
    return project_id, task_id


def exported(client, headers, project_id):
    response = client.get(f"/api/projects/{project_id}/export/json", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()


def regenerate(client, headers, project_id, expected_days):
    response = client.post(f"/api/projects/{project_id}/schedule/generate", headers=headers)
    assert response.status_code == 200, response.json()
    with SessionLocal() as db:
        entries = db.query(ScheduleEntry).filter_by(project_id=project_id).all()
        assert len({entry.work_date for entry in entries}) == expected_days
        assert sum(entry.planned_quantity for entry in entries) == pytest.approx(10)
        assert all(not entry.is_confirmed and not entry.is_locked for entry in entries)


def test_json_roundtrip_preserves_short_drafts_and_manual_budget(client, admin_headers):
    source_id, source_task = source_project(client, admin_headers)
    payload = exported(client, admin_headers, source_id)
    assert payload["planning_schedule"] == {
        "duration_scale": .5,
        "task_durations": [{"task_source_id": source_task, "workdays": 2,
                            "baseline_quantity": 10, "baseline_unit": "台", "is_active": True}],
    }
    payload["project"]["name"] = "Imported plan"
    response = client.post("/api/projects/import/json", headers=admin_headers, json=payload)
    assert response.status_code == 200, response.json()
    new_id = response.json()["id"]
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=new_id).one()
        budget = db.query(TaskDurationOverride).filter_by(task_id=task.id).one()
        assert task.id != source_task
        assert (budget.workdays, budget.baseline_quantity, budget.baseline_unit, budget.is_active) == (2, 10, "台", True)
        assert budget.version == 0 and budget.recovered_from_log_id is None
        assert budget.updated_by == db.query(User).filter_by(username="admin").one().id
        assert task.standard_hours == 4
        drafts = db.query(ScheduleEntry).filter_by(project_id=new_id).all()
        assert len(drafts) == 2 and all(not item.is_confirmed and item.assignee_id is None for item in drafts)
    regenerate(client, admin_headers, new_id, 2)


def test_clone_keeps_budget_but_starts_without_execution(client, admin_headers):
    source_id, source_task = source_project(client, admin_headers)
    with SessionLocal() as db:
        entry = db.query(ScheduleEntry).filter_by(project_id=source_id).first()
        entry.is_confirmed = True
        db.add(DailyProgress(project_id=source_id, task_id=source_task, schedule_entry_id=entry.id,
                             work_date=entry.work_date, user_id=db.query(User).filter_by(username="pm").one().id,
                             completed_quantity=1, client_uuid="clone-source-report"))
        db.commit()
    response = client.post(f"/api/projects/{source_id}/clone", headers=admin_headers, json={"name": "Cloned plan"})
    assert response.status_code == 200, response.json()
    new_id = response.json()["id"]
    with SessionLocal() as db:
        assert db.get(Project, new_id).status == "draft"
        assert db.query(ScheduleEntry).filter_by(project_id=new_id).count() == 0
        assert db.query(DailyProgress).filter_by(project_id=new_id).count() == 0
        task = db.query(Task).filter_by(project_id=new_id).one()
        budget = db.query(TaskDurationOverride).filter_by(task_id=task.id).one()
        assert (budget.workdays, budget.baseline_quantity, budget.is_active) == (2, 10, True)
        assert budget.version == 0 and budget.recovered_from_log_id is None
        assert budget.updated_by == db.query(User).filter_by(username="admin").one().id
        assert db.query(ProjectSchedulePolicy).filter_by(project_id=new_id).one().duration_scale == .5
        assert db.query(TaskDurationOverride).filter_by(task_id=source_task).one().version == 8
    regenerate(client, admin_headers, new_id, 2)


def test_old_json_without_preferences_remains_automatic(client, admin_headers):
    source_id, _ = source_project(client, admin_headers)
    payload = exported(client, admin_headers, source_id)
    payload.pop("planning_schedule", None)
    response = client.post("/api/projects/import/json", headers=admin_headers, json=payload)
    assert response.status_code == 200, response.json()
    new_id = response.json()["id"]
    with SessionLocal() as db:
        assert db.query(ProjectSchedulePolicy).filter_by(project_id=new_id).count() == 0
        assert db.query(TaskDurationOverride).filter_by(project_id=new_id).count() == 0
    regenerate(client, admin_headers, new_id, 5)


@pytest.mark.parametrize("entrypoint", ["import", "clone"])
def test_duplicate_task_names_keep_budgets_mapped_by_source_id(client, admin_headers, entrypoint):
    source_id, first_id = source_project(client, admin_headers)
    with SessionLocal() as db:
        first = db.get(Task, first_id)
        second = Task(project_id=source_id, module_id=first.module_id, name=first.name,
                      quantity_type="manual", target_quantity=20, unit="台", standard_hours=4)
        db.add(second)
        db.flush()
        db.add(TaskDurationOverride(task_id=second.id, project_id=source_id, workdays=3,
                                   baseline_quantity=20, baseline_unit="台", is_active=True))
        db.commit()
    if entrypoint == "import":
        response = client.post("/api/projects/import/json", headers=admin_headers,
                               json=exported(client, admin_headers, source_id))
    else:
        response = client.post(f"/api/projects/{source_id}/clone", headers=admin_headers, json={})
    assert response.status_code == 200, response.json()
    new_id = response.json()["id"]
    with SessionLocal() as db:
        copied = db.query(Task).filter_by(project_id=new_id).all()
        assert len(copied) == 2 and len({task.name for task in copied}) == 1
        assert {task.target_quantity: (db.get(TaskDurationOverride, task.id).workdays,
                                      db.get(TaskDurationOverride, task.id).baseline_quantity)
                for task in copied} == {10: (2, 10), 20: (3, 20)}
    response = client.post(f"/api/projects/{new_id}/schedule/generate", headers=admin_headers)
    assert response.status_code == 200, response.json()
    with SessionLocal() as db:
        for task in db.query(Task).filter_by(project_id=new_id).all():
            entries = db.query(ScheduleEntry).filter_by(task_id=task.id).all()
            assert len({entry.work_date for entry in entries}) == (2 if task.target_quantity == 10 else 3)
            assert sum(entry.planned_quantity for entry in entries) == pytest.approx(task.target_quantity)


def test_export_of_recoverable_legacy_budget_is_read_only(client, admin_headers):
    source_id, task_id = source_project(client, admin_headers)
    with SessionLocal() as db:
        db.delete(db.get(TaskDurationOverride, task_id))
        db.add(ChangeLog(project_id=source_id, entity_type="task", entity_id=task_id,
                         action="schedule_range", operator_id=db.query(User).filter_by(username="admin").one().id,
                         detail="调整工期：Policy task · 2026-11-02 至 2026-11-03 · 计划总量 10.0台 不变",
                         old_value={"start_date": "2026-11-02", "end_date": "2026-11-06", "entries": 5},
                         new_value={"start_date": "2026-11-02", "end_date": "2026-11-03", "distribution": [
                             {"work_date": "2026-11-02", "planned_quantity": 5},
                             {"work_date": "2026-11-03", "planned_quantity": 5},
                         ]}))
        db.commit()
    payload = exported(client, admin_headers, source_id)
    assert payload["planning_schedule"]["task_durations"][0]["workdays"] == 2
    with SessionLocal() as db:
        assert db.get(TaskDurationOverride, task_id) is None


@pytest.mark.parametrize("entrypoint", ["import", "clone"])
def test_explicit_automatic_survives_reuse_even_after_unit_change(client, admin_headers, entrypoint):
    source_id, _ = source_project(client, admin_headers, active=False, baseline_unit="米")
    if entrypoint == "import":
        payload = exported(client, admin_headers, source_id)
        assert payload["planning_schedule"]["task_durations"][0]["is_active"] is False
        response = client.post("/api/projects/import/json", headers=admin_headers, json=payload)
    else:
        response = client.post(f"/api/projects/{source_id}/clone", headers=admin_headers, json={})
    assert response.status_code == 200, response.json()
    new_id = response.json()["id"]
    with SessionLocal() as db:
        budget = db.query(TaskDurationOverride).filter_by(project_id=new_id).one()
        assert budget.is_active is False
    regenerate(client, admin_headers, new_id, 3)


@pytest.mark.parametrize("entrypoint", ["import", "clone"])
def test_legacy_missing_unit_preserves_effective_budget_unit(client, admin_headers, entrypoint):
    source_id, task_id = source_project(client, admin_headers)
    with SessionLocal() as db:
        db.get(Task, task_id).unit = None
        db.get(TaskDurationOverride, task_id).baseline_unit = "项"
        db.commit()
    if entrypoint == "import":
        response = client.post("/api/projects/import/json", headers=admin_headers,
                               json=exported(client, admin_headers, source_id))
    else:
        response = client.post(f"/api/projects/{source_id}/clone", headers=admin_headers, json={})
    assert response.status_code == 200, response.json()
    new_id = response.json()["id"]
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=new_id).one()
        assert task.unit == db.get(TaskDurationOverride, task.id).baseline_unit == "项"
    regenerate(client, admin_headers, new_id, 2)


def invalid_payload():
    return {
        "type": "agvpm-project",
        "project": {"name": "Rejected policy", "start_date": "2026-11-02", "end_date": "2026-12-31"},
        "modules": [{"phase_name": "现场实施", "name": "模块", "tasks": [
            {"source_id": "input-task", "name": "任务", "quantity_type": "manual", "target_quantity": 10, "unit": "台"},
        ]}],
        "planning_schedule": {"duration_scale": .5, "task_durations": [
            {"task_source_id": "input-task", "workdays": 2, "baseline_quantity": 10,
             "baseline_unit": "台", "is_active": True},
        ]},
    }


@pytest.mark.parametrize("field,value", [
    ("duration_scale", True), ("duration_scale", "0.5"), ("duration_scale", 0.1),
    ("duration_scale", 5), ("duration_scale", float("inf")),
    ("workdays", True), ("workdays", 2.0), ("workdays", 0), ("workdays", 3662),
    ("baseline_quantity", True), ("baseline_quantity", 0), ("baseline_quantity", -.1),
    ("baseline_quantity", .001), ("baseline_quantity", float("nan")),
    ("baseline_unit", "米"), ("baseline_unit", ""), ("baseline_unit", "台" * 21),
    ("is_active", "false"), ("task_source_id", "foreign-task"),
])
def test_invalid_policy_rejected_before_any_project_is_created(client, admin_headers, field, value):
    payload = invalid_payload()
    if field == "duration_scale":
        payload["planning_schedule"][field] = value
    else:
        payload["planning_schedule"]["task_durations"][0][field] = value
    with SessionLocal() as db:
        before = (db.query(Project).count(), db.query(Task).count(),
                  db.query(ProjectSchedulePolicy).count(), db.query(TaskDurationOverride).count())
    response = client.post("/api/projects/import/json", headers={**admin_headers, "Content-Type": "application/json"},
                           content=json.dumps(payload))
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert (db.query(Project).count(), db.query(Task).count(),
                db.query(ProjectSchedulePolicy).count(), db.query(TaskDurationOverride).count()) == before


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "unknown", "size", "wrong-shape"])
def test_policy_collection_rejects_ambiguous_or_untrusted_fields(client, admin_headers, mutation):
    payload = invalid_payload()
    records = payload["planning_schedule"]["task_durations"]
    if mutation == "duplicate":
        records.append(deepcopy(records[0]))
    elif mutation == "missing":
        del records[0]["baseline_quantity"]
    elif mutation == "unknown":
        records[0]["is_confirmed"] = True
    elif mutation == "size":
        payload["planning_schedule"]["task_durations"] = records * 5001
    else:
        payload["planning_schedule"] = []
    with SessionLocal() as db:
        before = db.query(Project).count()
    response = client.post("/api/projects/import/json", headers=admin_headers, json=payload)
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.query(Project).count() == before


def test_worker_cannot_import_or_clone_planning_preferences(client, admin_headers, worker_headers):
    source_id, _ = source_project(client, admin_headers)
    assert client.post("/api/projects/import/json", headers=worker_headers, json=invalid_payload()).status_code == 403
    assert client.post(f"/api/projects/{source_id}/clone", headers=worker_headers, json={}).status_code == 403


def test_active_sparse_budget_fails_preview_and_import_without_partial_creation(client, admin_headers):
    payload = invalid_payload()
    payload["planning_schedule"]["task_durations"][0].update(workdays=3, baseline_quantity=.01)
    with SessionLocal() as db:
        before = (db.query(Project).count(), db.query(Task).count(),
                  db.query(ProjectSchedulePolicy).count(), db.query(TaskDurationOverride).count())
    preview = client.post("/api/projects/import/preview", headers=admin_headers, json=payload)
    assert preview.status_code == 200
    assert preview.json()["valid"] is False
    assert any("0.02" in error for error in preview.json()["errors"])
    imported = client.post("/api/projects/import/json", headers=admin_headers, json=payload)
    assert imported.status_code == 400 and "0.02" in imported.json()["detail"]
    with SessionLocal() as db:
        assert (db.query(Project).count(), db.query(Task).count(),
                db.query(ProjectSchedulePolicy).count(), db.query(TaskDurationOverride).count()) == before


def test_inactive_tombstone_does_not_apply_sparse_budget_rule(client, admin_headers):
    payload = invalid_payload()
    payload["planning_schedule"]["task_durations"][0].update(workdays=3, baseline_quantity=.01, is_active=False)
    imported = client.post("/api/projects/import/json", headers=admin_headers, json=payload)
    assert imported.status_code == 200, imported.json()
    new_id = imported.json()["id"]
    with SessionLocal() as db:
        assert db.query(TaskDurationOverride).filter_by(project_id=new_id).one().is_active is False
    # The unused legacy rate cannot resurrect an impossible manual duration.
    regenerate(client, admin_headers, new_id, 3)


def reference_fixture(task_id):
    from app.config import UPLOAD_DIR
    directory = UPLOAD_DIR
    directory.mkdir(parents=True, exist_ok=True)
    content = "QA reference: clone copies planning documentation independently.\n".encode()
    stored = "reference-original.txt"
    (directory / stored).write_bytes(content)
    with SessionLocal() as db:
        db.get(Task, task_id).reference_docs = [{"stored_name": stored, "filename": "QA reference.txt", "size": len(content)}]
        db.commit()
    return directory, stored, content


def test_invalid_clone_budget_rejects_before_reference_files_or_project_are_copied(client, admin_headers, monkeypatch, tmp_path):
    source_id, source_task = source_project(client, admin_headers)
    directory, stored, content = reference_fixture(source_task)
    models = (Project, Phase, Module, Task, ScheduleEntry, DailyProgress,
              ProjectSchedulePolicy, TaskDurationOverride, ChangeLog)
    with SessionLocal() as db:
        db.get(Task, source_task).unit = "个"
        db.commit()
        before_rows = {model.__name__: db.query(model).count() for model in models}
    before_files = {file.name: file.read_bytes() for file in directory.iterdir()}
    response = client.post(f"/api/projects/{source_id}/clone", headers=admin_headers,
                           json={"name": "Invalid budget clone", "start_date": "2026-11-01", "end_date": "2026-12-31"})
    assert response.status_code == 400 and "baseline_unit" in response.json()["detail"]
    with SessionLocal() as db:
        assert {model.__name__: db.query(model).count() for model in models} == before_rows
        assert db.get(Task, source_task).reference_docs[0]["stored_name"] == stored
    assert {file.name: file.read_bytes() for file in directory.iterdir()} == before_files
    assert (directory / stored).read_bytes() == content


def test_valid_clone_budget_still_copies_reference_file_independently(client, admin_headers, monkeypatch, tmp_path):
    source_id, source_task = source_project(client, admin_headers)
    directory, stored, content = reference_fixture(source_task)
    original_names = {file.name for file in directory.iterdir()}
    response = client.post(f"/api/projects/{source_id}/clone", headers=admin_headers,
                           json={"name": "Valid budget clone"})
    assert response.status_code == 200, response.json()
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=response.json()["id"]).one()
        copied_name = task.reference_docs[0]["stored_name"]
        assert copied_name != stored
        assert db.get(TaskDurationOverride, task.id).workdays == 2
        assert db.get(Task, source_task).reference_docs[0]["stored_name"] == stored
    assert {file.name for file in directory.iterdir()} == original_names | {copied_name}
    assert (directory / copied_name).read_bytes() == (directory / stored).read_bytes() == content
    (directory / copied_name).write_bytes(b"QA independent clone document update\n")
    assert (directory / stored).read_bytes() == content
