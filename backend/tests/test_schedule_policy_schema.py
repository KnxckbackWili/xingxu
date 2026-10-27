"""Additive scheduling-policy schema checks; every database here is in memory.

These tests exercise schema/restore compatibility and database constraints.
They do not replace the service/API duration or real PostgreSQL checks.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine, delete, event, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.db import Base
from app.models import (
    DailyProgress,
    Module,
    Phase,
    Project,
    ProjectSchedulePolicy,
    ScheduleEntry,
    Task,
    TaskDurationOverride,
    User,
)


POLICY_TABLES = {ProjectSchedulePolicy.__table__.name, TaskDurationOverride.__table__.name}


@pytest.fixture
def legacy_sqlite():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    legacy_tables = [table for table in Base.metadata.sorted_tables if table.name not in POLICY_TABLES]
    Base.metadata.create_all(engine, tables=legacy_tables)
    with engine.begin() as connection:
        connection.execute(User.__table__.insert(), {
            "id": "schema-user", "username": "schema-user", "display_name": "Schema fixture",
            "password_hash": "not-a-real-password-hash", "role": "admin",
        })
        connection.execute(Project.__table__.insert(), {
            "id": "schema-project", "name": "Legacy project", "manager": "schema-user",
            "members": ["schema-user"], "start_date": date(2026, 1, 5),
            "end_date": date(2026, 12, 31), "status": "executing",
        })
        connection.execute(Phase.__table__.insert(), {
            "id": "schema-phase", "project_id": "schema-project", "name": "Implementation",
        })
        connection.execute(Module.__table__.insert(), {
            "id": "schema-module", "project_id": "schema-project", "phase_id": "schema-phase",
            "name": "Commissioning",
        })
        connection.execute(Task.__table__.insert(), [
            {"id": task_id, "project_id": "schema-project", "module_id": "schema-module",
             "name": task_id, "quantity_type": "manual", "target_quantity": 10,
             "unit": "台", "standard_hours": 4}
            for task_id in ("schema-task", "schema-task-auto")
        ])
        connection.execute(ScheduleEntry.__table__.insert(), {
            "id": "schema-entry", "project_id": "schema-project", "task_id": "schema-task",
            "work_date": date(2026, 1, 5), "assignee_id": "schema-user",
            "planned_quantity": 10, "is_confirmed": True, "is_locked": True, "version": 7,
        })
        connection.execute(DailyProgress.__table__.insert(), {
            "id": "schema-report", "project_id": "schema-project", "task_id": "schema-task",
            "schedule_entry_id": "schema-entry", "work_date": date(2026, 1, 5),
            "user_id": "schema-user", "completed_quantity": 2, "client_uuid": "schema-report-uuid",
        })
    try:
        yield engine, legacy_tables
    finally:
        engine.dispose()


def rows(engine, tables):
    with engine.connect() as connection:
        return {
            table.name: connection.execute(select(table).order_by(*table.primary_key.columns)).all()
            for table in tables
        }


def add_preferences(engine):
    with engine.begin() as connection:
        connection.execute(ProjectSchedulePolicy.__table__.insert(), {
            "project_id": "schema-project", "duration_scale": .5, "version": 3,
            "updated_by": "schema-user",
        })
        connection.execute(TaskDurationOverride.__table__.insert(), [
            {"task_id": "schema-task", "project_id": "schema-project", "workdays": 2,
             "baseline_quantity": 10, "baseline_unit": "台", "is_active": True,
             "recovered_from_log_id": "legacy-resize-log", "version": 4,
             "updated_by": "schema-user"},
            {"task_id": "schema-task-auto", "project_id": "schema-project", "workdays": 2,
             "baseline_quantity": 10, "baseline_unit": "台", "is_active": False,
             "recovered_from_log_id": None, "version": 5, "updated_by": "schema-user"},
        ])


def test_policy_tables_add_without_rewriting_legacy_sqlite(legacy_sqlite):
    engine, legacy_tables = legacy_sqlite
    old_names = set(inspect(engine).get_table_names())
    old_columns = {
        table.name: [column["name"] for column in inspect(engine).get_columns(table.name)]
        for table in legacy_tables
    }
    before = rows(engine, legacy_tables)

    Base.metadata.create_all(engine)

    assert set(inspect(engine).get_table_names()) == old_names | POLICY_TABLES
    assert rows(engine, legacy_tables) == before
    for table in legacy_tables:
        assert [column["name"] for column in inspect(engine).get_columns(table.name)] == old_columns[table.name]
    assert rows(engine, [ProjectSchedulePolicy.__table__, TaskDurationOverride.__table__]) == {
        "project_schedule_policies": [], "task_duration_overrides": [],
    }


def test_create_all_again_retains_manual_and_automatic_tombstone(legacy_sqlite):
    engine, legacy_tables = legacy_sqlite
    Base.metadata.create_all(engine)
    add_preferences(engine)
    tables = legacy_tables + [ProjectSchedulePolicy.__table__, TaskDurationOverride.__table__]
    before = rows(engine, tables)

    Base.metadata.create_all(engine)

    assert rows(engine, tables) == before


@pytest.mark.parametrize("parent", ["task", "project"])
def test_policy_cascade_follows_parent_only(legacy_sqlite, parent):
    engine, _ = legacy_sqlite
    Base.metadata.create_all(engine)
    add_preferences(engine)
    with engine.begin() as connection:
        if parent == "task":
            connection.execute(delete(Task).where(Task.id == "schema-task"))
        else:
            connection.execute(delete(Project).where(Project.id == "schema-project"))
    remaining = rows(engine, [ProjectSchedulePolicy.__table__, TaskDurationOverride.__table__])
    if parent == "task":
        assert len(remaining["project_schedule_policies"]) == 1
        assert [row.task_id for row in remaining["task_duration_overrides"]] == ["schema-task-auto"]
        assert remaining["task_duration_overrides"][0].is_active is False
    else:
        assert remaining == {"project_schedule_policies": [], "task_duration_overrides": []}


@pytest.mark.parametrize("model,values", [
    (ProjectSchedulePolicy, {"project_id": "missing-project"}),
    (TaskDurationOverride, {"task_id": "missing-task", "project_id": "schema-project"}),
    (TaskDurationOverride, {"task_id": "schema-task", "project_id": "missing-project"}),
])
def test_sqlite_policy_foreign_keys_reject_orphans(legacy_sqlite, model, values):
    engine, legacy_tables = legacy_sqlite
    Base.metadata.create_all(engine)
    before = rows(engine, legacy_tables)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(model.__table__.insert(), values)
    assert rows(engine, legacy_tables) == before


@pytest.mark.parametrize("model,primary_key,parents", [
    (ProjectSchedulePolicy, "project_id", {"projects.id"}),
    (TaskDurationOverride, "task_id", {"projects.id", "tasks.id"}),
])
def test_postgres_ddl_keeps_parent_keys_and_cascade(model, primary_key, parents):
    table = model.__table__
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert list(table.primary_key.columns.keys()) == [primary_key]
    assert {key.target_fullname for key in table.foreign_keys} == parents
    assert all(key.ondelete == "CASCADE" for key in table.foreign_keys)
    assert f"PRIMARY KEY ({primary_key})" in ddl
    assert ddl.count("ON DELETE CASCADE") == len(parents)
