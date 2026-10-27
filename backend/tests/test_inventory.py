"""Project inventory ownership, movement, scope and portability tests."""


def _project(client, headers, name="物品测试项目"):
    response = client.post("/api/projects", headers=headers, json={
        "name": name, "start_date": "2026-08-01", "end_date": "2026-12-31",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_inventory_crud_movements_and_global_view(client, pm_headers, worker_headers):
    project_id = _project(client, pm_headers)
    company = client.post(f"/api/projects/{project_id}/inventory", headers=pm_headers, json={
        "item_code": "TOOL-01", "name": "激光测距仪", "category": "tool",
        "ownership": "company", "tracking_mode": "serial", "serial_number": "SN-01",
        "quantity": 1, "unit": "台", "status": "on_site", "location": "工具柜 A", "custodian": "张工",
    })
    assert company.status_code == 200, company.text
    client_item = client.post(f"/api/projects/{project_id}/inventory", headers=pm_headers, json={
        "item_code": "CLIENT-KEY", "name": "甲方门禁钥匙", "category": "other",
        "ownership": "client", "tracking_mode": "quantity", "quantity": 3,
        "minimum_quantity": 1, "unit": "把", "status": "on_site", "location": "项目办公室",
    })
    assert client_item.status_code == 200, client_item.text

    moved = client.post(
        f"/api/projects/{project_id}/inventory/{client_item.json()['id']}/movements", headers=pm_headers,
        json={"movement_type": "issue", "quantity": 2, "to_location": "施工区", "handler": "李工", "note": "发放施工人员"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["item"]["quantity"] == 1
    assert moved.json()["movement"]["balance_after"] == 1
    assert client.post(
        f"/api/projects/{project_id}/inventory/{client_item.json()['id']}/movements", headers=pm_headers,
        json={"movement_type": "consume", "quantity": 2},
    ).status_code == 400

    listing = client.get(f"/api/projects/{project_id}/inventory?ownership=client", headers=pm_headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["low_stock"] is True
    assert listing["summary"]["company_records"] == 1
    assert listing["summary"]["client_records"] == 1
    global_view = client.get("/api/inventory", headers=pm_headers).json()
    assert global_view["total"] == 2
    assert global_view["summary"]["project_count"] == 1

    # Ordinary workers cannot discover or modify an unassigned project.
    assert client.get(f"/api/projects/{project_id}/inventory", headers=worker_headers).status_code == 404
    assert client.post(f"/api/projects/{project_id}/inventory", headers=worker_headers, json={
        "name": "越权物品", "quantity": 1,
    }).status_code == 404


def test_inventory_movement_timezone_and_retry_share_one_instant(client, pm_headers):
    pid = _project(client, pm_headers)
    item = client.post(f"/api/projects/{pid}/inventory", headers=pm_headers,
                       json={"name": "时区验收物品", "quantity": 2}).json()
    endpoint = f"/api/projects/{pid}/inventory/{item['id']}/movements"
    payload = {"movement_type": "issue", "quantity": 1, "client_uuid": "timezone-operation-01",
               "occurred_at": "2026-10-05T03:49:00+08:00"}
    result = client.post(endpoint, headers=pm_headers, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["movement"]["occurred_at"] == "2026-10-04T19:49:00"
    assert result.json()["movement"]["time_basis"] == "utc"
    retry = client.post(endpoint, headers=pm_headers,
                        json={**payload, "occurred_at": "2026-10-04T19:49:00Z"})
    assert retry.status_code == 200, retry.text
    assert retry.json()["accepted"] is False and retry.json()["item"]["quantity"] == 1


def test_inventory_bulk_import_and_json_roundtrip(client, pm_headers):
    project_id = _project(client, pm_headers, "批量物品项目")
    imported = client.post(f"/api/projects/{project_id}/inventory/import", headers=pm_headers, json={"items": [
        {"name": "交换机", "category": "equipment", "ownership": "company", "quantity": 2, "unit": "台", "location": "控制柜"},
        {"name": "甲方操作手册", "category": "document", "ownership": "client", "quantity": 1, "unit": "份", "expected_return_date": "2026-12-30"},
    ]})
    assert imported.status_code == 200, imported.text
    snapshot = client.get(f"/api/projects/{project_id}/export/json", headers=pm_headers).json()
    assert snapshot["version"] == "2.4"
    assert len(snapshot["inventory_items"]) == 2
    assert snapshot["inventory_items"][0]["movements"][0]["movement_type"] == "inventory"
    restored = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot)
    assert restored.status_code == 200, restored.text
    rows = client.get(f"/api/projects/{restored.json()['id']}/inventory", headers=pm_headers).json()["items"]
    assert {row["ownership"] for row in rows} == {"company", "client"}


def test_serial_item_rejects_multi_quantity(client, pm_headers):
    project_id = _project(client, pm_headers, "序列号物品项目")
    response = client.post(f"/api/projects/{project_id}/inventory", headers=pm_headers, json={
        "name": "示波器", "tracking_mode": "serial", "quantity": 2, "unit": "台",
    })
    assert response.status_code == 400


def test_inventory_legacy_time_basis_survives_json_roundtrip(client, pm_headers):
    from datetime import datetime
    from sqlalchemy import text
    from app.db import SessionLocal
    from app.models import ProjectInventoryMovement
    pid = _project(client, pm_headers)
    item = client.post(f"/api/projects/{pid}/inventory", headers=pm_headers,
                       json={"name": "历史时间测试", "quantity": 2}).json()
    endpoint = f"/api/projects/{pid}/inventory/{item['id']}/movements"
    with SessionLocal() as db:
        old = ProjectInventoryMovement(project_id=pid, item_id=item["id"], movement_type="issue",
            quantity=1, balance_after=1, occurred_at=datetime(2026, 10, 5, 3, 10), note="历史手工领用")
        db.add(old); db.flush()
        # Mimic an existing database after the additive nullable-column migration.
        db.execute(text("UPDATE project_inventory_movements SET time_basis = NULL WHERE item_id=:id"), {"id": item["id"]})
        db.commit()
    history = client.get(endpoint, headers=pm_headers).json()
    assert next(m for m in history if m["note"] == "历史手工领用")["time_basis"] == "legacy_local"
    assert next(m for m in history if m["note"] == "建立台账时的初始数量")["time_basis"] == "utc"
    old_client = client.post(endpoint, headers=pm_headers, json={"movement_type": "transfer", "quantity": 2,
        "occurred_at": "2026-10-05T03:12:00", "note": "旧客户端记录"})
    assert old_client.status_code == 200, old_client.text
    assert old_client.json()["movement"]["time_basis"] == "legacy_local"
    snapshot = client.get(f"/api/projects/{pid}/export/json", headers=pm_headers).json()
    # Historical JSON exports lack provenance; old manual contract remains local.
    for movement in snapshot["inventory_items"][0]["movements"]:
        movement.pop("time_basis", None)
    restored = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot)
    assert restored.status_code == 200, restored.text
    rows = client.get(f"/api/projects/{restored.json()['id']}/inventory", headers=pm_headers).json()["items"]
    history = client.get(f"/api/projects/{restored.json()['id']}/inventory/{rows[0]['id']}/movements", headers=pm_headers).json()
    manual = next(m for m in history if m["note"] == "历史手工领用")
    assert manual["occurred_at"] == "2026-10-05T03:10:00" and manual["time_basis"] == "legacy_local"
    assert next(m for m in history if m["note"] == "建立台账时的初始数量")["time_basis"] == "utc"


def test_inventory_retry_cannot_change_the_timestamp_basis(client, pm_headers):
    pid = _project(client, pm_headers)
    item = client.post(f"/api/projects/{pid}/inventory", headers=pm_headers,
                       json={"name": "时间语义重试测试", "quantity": 2}).json()
    endpoint = f"/api/projects/{pid}/inventory/{item['id']}/movements"
    payload = {"movement_type": "issue", "quantity": 1, "client_uuid": "legacy-operation-01",
               "occurred_at": "2026-10-05T03:10:00"}
    assert client.post(endpoint, headers=pm_headers, json=payload).status_code == 200
    assert client.post(endpoint, headers=pm_headers, json=payload).json()["accepted"] is False
    assert client.post(endpoint, headers=pm_headers,
                       json={**payload, "occurred_at": "2026-10-05T03:10:00Z"}).status_code == 409
