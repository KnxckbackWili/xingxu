import pytest
"""Project inventory ownership, movement, scope and portability tests."""


def _project(client, headers, name="物品测试项目"):
    response = client.post("/api/projects", headers=headers, json={
        "name": name, "start_date": "2026-08-01", "end_date": "2026-12-31",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


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


