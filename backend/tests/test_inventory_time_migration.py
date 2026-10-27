"""库存时间来源的存量迁移与跨时区 JSON 兼容回归。"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import inspect, text


def test_inventory_time_basis_frozen_postgres_column_keeps_unknown_provenance():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateColumn
    from migrations.v243_schema import metadata
    column = metadata.tables['project_inventory_movements'].c.time_basis
    assert str(CreateColumn(column).compile(dialect=postgresql.dialect())) == 'time_basis VARCHAR(20)'
    assert column.nullable and column.server_default is None


def test_inventory_time_basis_migration_preserves_existing_rows(client, pm_headers, upgrade_legacy_schema):
    """真实旧表补列与二次启动都不得改写原流水的墙钟值。"""
    from app.db import engine, SessionLocal
    from app.models import ProjectInventoryMovement

    project = client.post("/api/projects", headers=pm_headers, json={
        "name": "库存时间迁移回归", "start_date": "2026-08-01", "end_date": "2026-12-31",
    })
    assert project.status_code == 200, project.text
    pid = project.json()["id"]
    item = client.post(f"/api/projects/{pid}/inventory", headers=pm_headers,
                       json={"name": "历史流水物品", "quantity": 0})
    assert item.status_code == 200, item.text
    with SessionLocal() as db:
        movement = ProjectInventoryMovement(project_id=pid, item_id=item.json()["id"],
            movement_type="transfer", quantity=1, balance_after=0,
            occurred_at=datetime(2026, 10, 5, 3, 10), note="历史墙钟值")
        db.add(movement)
        db.flush()
        movement_id = movement.id
        db.commit()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE project_inventory_movements DROP COLUMN time_basis"))
    upgrade_legacy_schema()
    from app.db import _alembic_sync_schema
    _alembic_sync_schema()
    with SessionLocal() as db:
        row = db.execute(text("SELECT occurred_at, time_basis FROM project_inventory_movements WHERE id=:id"),
                         {"id": movement_id}).one()
        value = row[0] if isinstance(row[0], datetime) else datetime.fromisoformat(row[0])
        assert value == datetime(2026, 10, 5, 3, 10)
        assert row[1] is None
    column = next(column for column in inspect(engine).get_columns("project_inventory_movements")
                  if column["name"] == "time_basis")
    assert column["nullable"] and column["default"] is None


@pytest.mark.parametrize("aware_time,source_basis", [
    ("2026-10-05T03:49:00+08:00", "legacy_local"),
    ("2026-10-04T19:49:00Z", "utc"),
    ("2026-10-04T15:49:00-04:00", None),
])
def test_inventory_json_aware_time_and_explicit_basis_roundtrip(client, pm_headers, aware_time, source_basis):
    project = client.post("/api/projects", headers=pm_headers, json={
        "name": "库存跨时区 JSON 回归", "start_date": "2026-08-01", "end_date": "2026-12-31",
    })
    assert project.status_code == 200, project.text
    pid = project.json()["id"]
    item = client.post(f"/api/projects/{pid}/inventory", headers=pm_headers,
                       json={"name": "跨时区物品", "quantity": 2})
    assert item.status_code == 200, item.text
    snapshot = client.get(f"/api/projects/{pid}/export/json", headers=pm_headers).json()
    snapshot["inventory_items"][0]["movements"] = [
        {"movement_type": "transfer", "quantity": 1, "balance_after": 2,
         "occurred_at": aware_time, "time_basis": source_basis, "note": "带时区的同一时刻"},
        {"movement_type": "transfer", "quantity": 1, "balance_after": 2,
         "occurred_at": "2026-10-05T03:10:00", "time_basis": "legacy_local", "note": "保留手工墙钟"},
        {"movement_type": "transfer", "quantity": 1, "balance_after": 2,
         "occurred_at": "2026-10-04T19:49:00", "time_basis": "utc", "note": "保留 UTC 来源"},
    ]
    imported = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot)
    assert imported.status_code == 200, imported.text
    exported = client.get(f"/api/projects/{imported.json()['id']}/export/json", headers=pm_headers).json()
    movements = {movement["note"]: movement for movement in exported["inventory_items"][0]["movements"]}
    assert (movements["带时区的同一时刻"]["occurred_at"], movements["带时区的同一时刻"]["time_basis"]) == (
        "2026-10-04T19:49:00", "utc")
    assert (movements["保留手工墙钟"]["occurred_at"], movements["保留手工墙钟"]["time_basis"]) == (
        "2026-10-05T03:10:00", "legacy_local")
    assert (movements["保留 UTC 来源"]["occurred_at"], movements["保留 UTC 来源"]["time_basis"]) == (
        "2026-10-04T19:49:00", "utc")
