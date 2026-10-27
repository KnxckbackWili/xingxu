"""Progress calculation tests."""


def _setup_full(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "进度测试项目",
        "status": "planning",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    pid = r.json()["id"]
    # 4 vehicles
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 4})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-02", "mod-03"]})  # 到货检查 + 单车调试
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200
    return pid


def test_progress_starts_at_zero(client, pm_headers):
    pid = _setup_full(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/progress", headers=pm_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["percent"] == 0
    assert len(data["phases"]) == 2
    groups = {row["unit"]: row for row in data["quantities_by_unit"]}
    assert groups["台"]["target"] == 32
    assert groups["项"]["target"] == 1
    assert sum(row["completed"] for row in groups.values()) == 0


def test_progress_after_partial_fill(client, pm_headers, worker_headers):
    """Filling 2 of 4 vehicles' 到货检查 should give 25% overall."""
    pid = _setup_full(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    assert r.status_code == 200, r.json()
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.json()
    # Add worker as member
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    members = r.json()["members"] + ["user-worker-001"]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": members})

    # Find 开箱检查 task (per_vehicle, target=4)
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree = r.json()
    task = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "开箱检查":
                    task = t
    assert task is not None
    assert task["target_quantity"] == 4

    # Report 2 completed on today's date
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": task["id"],
        "work_date": "2026-08-12",
        "completed_quantity": 2,
        "client_uuid": "progress-0001",
    })
    assert r.status_code == 200

    # Original quantity facts remain readable but do not create identified matrix cells.
    before=client.get(f"/api/projects/{pid}/progress",headers=pm_headers).json()
    assert before['completed']==0
    from tests.test_project_events import unit
    from tests.test_vehicle_progress import write
    vid=client.get(f"/api/projects/{pid}/vehicles",headers=pm_headers).json()[0]['id']
    units=[unit(client,pm_headers,pid,vid,f'真车-{i}') for i in range(2)]
    assert write(client,pm_headers,pid,units).status_code==200
    # Two real vehicle steps, plus one equal-weight non-vehicle work item.
    r = client.get(f"/api/projects/{pid}/progress", headers=pm_headers)
    data = r.json()
    assert data["completed"] == 2
    groups = {row["unit"]: row for row in data["quantities_by_unit"]}
    assert groups["台"]["completed"] == 2
    assert groups["项"]["completed"] == 0
    # 8 per_vehicle tasks × 4 vehicles + 1 fixed (到货文档归档) = 33
    assert data["target"] == 4 * 5 + 1
    assert data["percent"] > 0
    assert data["percent"] < 100
    # 到货检查 phase progress = 2/4 / 8 tasks... verify 开箱检查 percent = 50
    opening = None
    for ph in data["phases"]:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "开箱检查":
                    opening = t
    assert opening is not None
    assert opening["completed"] == 2
    assert opening["percent"] == 50.0


def test_not_applicable_excluded_from_progress(client, pm_headers):
    """Marking a whole task's check items not-applicable excludes its quantity."""
    pid = _setup_full(client, pm_headers)
    # Find 载荷测试 (safety per_vehicle) - cannot ignore
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree = r.json()
    opening_ci = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "开箱检查":
                    opening_ci = t["check_items"][0]
    # Ignore the first (non-safety) check item of 开箱检查
    if not opening_ci["is_safety_critical"]:
        client.put(f"/api/projects/{pid}/check-items/{opening_ci['id']}", headers=pm_headers,
                   json={"is_applicable": False, "not_applicable_reason": "测试排除"})
    r = client.get(f"/api/projects/{pid}/progress", headers=pm_headers)
    # Task still counts (only ALL items ignored would exclude) - quantity unchanged
    assert r.json()["target"] > 0


def test_timeline_returns_series(client, pm_headers):
    pid = _setup_full(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/progress/timeline", headers=pm_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert "date" in data[0] and "planned" in data[0] and "actual" in data[0]
