from tests.lifecycle_helpers import versioned
"""P2-体验：项目级时区（俄/越现场）。

项目可配置 IANA 时区；"今日任务/撤回窗口"按项目现场时区取当地今天，
与服务器（默认上海）日历日可能相差一天。
"""


def _create_project(client, pm_headers, timezone="Asia/Shanghai", name="时区项目"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name,
        "status": "planning",
        "start_date": "2026-08-10",
        "new_vehicles": False,
        "end_date": "2026-09-30",
        "timezone": timezone,
    })
    assert r.status_code == 200, r.json()
    return r.json()


def _schedule_project(client, pm_headers, pid, worker_id="user-worker-001"):
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": [worker_id]}))
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.json()
    issued = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert issued.status_code == 200, issued.text


def test_project_timezone_default_and_read(client, pm_headers):
    p = _create_project(client, pm_headers)
    assert p["timezone"] == "Asia/Shanghai"


def test_project_timezone_custom_and_update(client, pm_headers):
    p = _create_project(client, pm_headers, timezone="Europe/Moscow")
    assert p["timezone"] == "Europe/Moscow"
    # 可更新时区
    r = client.put(f"/api/projects/{p['id']}", headers=pm_headers, json=versioned(p['id'], {"timezone": "Asia/Ho_Chi_Minh"}))
    assert r.status_code == 200, r.json()
    assert r.json()["timezone"] == "Asia/Ho_Chi_Minh"


def test_project_invalid_timezone_rejected(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "非法时区项目", "start_date": "2026-08-10",
        "new_vehicles": False, "end_date": "2026-09-30",
        "timezone": "Mars/Olympus",
    })
    assert r.status_code == 400


def test_worker_today_uses_project_local_today(client, pm_headers, worker_headers):
    """/worker/today?project_id=… 按项目现场时区取"当地今天"命中当日任务。"""
    from app.time_utils import today_in
    tz = "Europe/Moscow"
    p = _create_project(client, pm_headers, timezone=tz)
    pid = p["id"]
    _schedule_project(client, pm_headers, pid)

    entries = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()
    assert entries, "应有排程条目"
    eid = entries[0]["id"]

    # 把该条目日期改成项目当地今天（模拟俄现场当天任务）
    local_today = today_in(tz)
    r = client.put(f"/api/schedule/{eid}", headers=pm_headers,
                   json={"work_date": local_today.isoformat()})
    assert r.status_code == 200, r.json()

    # 不带 project_id（多项目合并视图）→ date 为服务器参考今天；items 可能为空（取决于机器时区）
    r = client.get("/api/worker/today", headers=worker_headers)
    assert r.status_code == 200
    assert "items" in r.json()

    # 带 project_id → 按项目时区过滤并返回项目当地今天
    r = client.get("/api/worker/today", headers=worker_headers, params={"project_id": pid})
    assert r.status_code == 200
    data = r.json()
    assert data["date"] == local_today.isoformat()
    assert any(item["entry_id"] == eid for item in data["items"])
    assert data["items"][0]["timezone"] == tz


def test_retract_window_uses_project_local_today(client, pm_headers, worker_headers):
    """撤回填报按项目时区判定"今天"，而非服务器上海日期。"""
    from app.time_utils import today_in
    tz = "Europe/Moscow"
    p = _create_project(client, pm_headers, timezone=tz)
    pid = p["id"]
    _schedule_project(client, pm_headers, pid)

    entries = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()
    entry = next((e for e in entries if e["planned_quantity"] > 0), entries[0])
    local_today = today_in(tz)

    # 填报一条"当地今天"的记录
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"],
        "schedule_entry_id": entry["id"],
        "work_date": local_today.isoformat(),
        "completed_quantity": 1,
        "note": "莫斯科现场填报",
        "client_uuid": "tz-report-0001",
    })
    assert r.status_code == 200, r.json()
    report_id = r.json()["id"]

    # 撤回窗口按项目时区 = 当地今天 → 可撤回（若服务器是上海且日期相同亦通过）
    r = client.delete(f"/api/worker/reports/{report_id}", headers=worker_headers)
    assert r.status_code == 200, r.json()
