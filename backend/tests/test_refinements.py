"""Refinement tests: work-definition permissions + check item ticking (v3: quantities are read-only)."""
from tests.lifecycle_helpers import versioned


def _project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "完善功能测试项目",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 3})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-01", "mod-03"]})
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    from tests.lifecycle_helpers import enter_execution
    enter_execution(client, pm_headers, pid)  # 检查项只在现场实施期间登记
    return pid


def _check_put(client, headers, pid, check_id, body):
    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        version = db.get(CheckItem, check_id).version or 0
    return client.put(f"/api/projects/{pid}/check-items/{check_id}", headers=headers, json={**body, "version": version})


def _find_task(client, pm_headers, pid, name):
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    for ph in r.json():
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == name:
                    return t
    return None


def test_worker_cannot_edit_task(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    task = _find_task(client, pm_headers, pid, "场地勘测")
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=worker_headers, json=versioned(task['id'], {"target_quantity": 9}, 'Task'))
    assert r.status_code in (403, 404)


def test_worker_ticks_check_item(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    # 逐车工作的检查在车辆进度表登记；这里使用项目级工作「场地勘测」的检查项。
    task = _find_task(client, pm_headers, pid, "场地勘测")
    assert task is not None
    ci = task["check_items"][0]
    assert ci["is_done"] is False

    # Worker ticks it
    r = _check_put(client, worker_headers, pid, ci['id'], {"is_done": True})
    assert r.status_code == 200, r.json()
    assert r.json()["is_done"] is True
    assert r.json()["done_by"] == "user-worker-001"

    # Tree reflects it
    task2 = _find_task(client, pm_headers, pid, "场地勘测")
    ci2 = next(c for c in task2["check_items"] if c["id"] == ci["id"])
    assert ci2["is_done"] is True

    # Untick
    r = _check_put(client, worker_headers, pid, ci['id'], {"is_done": False})
    assert r.status_code == 200
    assert r.json()["is_done"] is False


def test_worker_not_applicable_requires_reason_and_preserves_safety_guard(client, pm_headers, worker_headers):
    """三态流程允许成员跳过非安全项；原因必填，安全项永不可跳过。

    CLAUDE.md「检查项三态」及 TodayPage 明确 worker 可用，不再沿用旧 PM-only 契约。
    """
    pid = _project(client, pm_headers)
    task = _find_task(client, pm_headers, pid, "场地勘测")
    ci = next(c for c in task["check_items"] if not c["is_safety_critical"])

    response = _check_put(client, worker_headers, pid, ci['id'], {"is_applicable": False})
    assert response.status_code == 400
    assert "原因" in response.json()["detail"]
    response = _check_put(client, worker_headers, pid, ci['id'],
                          {"is_applicable": False, "not_applicable_reason": "现场未配置该功能"})
    assert response.status_code == 200, response.text
    assert response.json()["is_applicable"] is False

    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        row = db.get(CheckItem, ci["id"])
        row.is_applicable = True
        row.is_safety_critical = True
        db.commit()
    response = _check_put(client, worker_headers, pid, ci['id'],
                          {"is_applicable": False, "not_applicable_reason": "安全项不能跳过"})
    assert response.status_code == 400
    assert "安全" in response.json()["detail"]
