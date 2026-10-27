"""Auto-scheduling tests."""


def _project_with_tasks(client, pm_headers):
    """Create a project with vehicles + generated tasks."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "排程测试项目",
        "status": "planning",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 5})
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": [f"mod-{i:02d}" for i in range(1, 9)]})
    assert r.status_code == 200
    return pid


def test_schedule_generation(client, pm_headers):
    pid = _project_with_tasks(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.json()
    data = r.json()
    assert data["entries"] > 20
    assert data["total_hours"] > 0
    # All entries within project date range
    # 任务量可能超出周期 — 系统应返回警告而非静默失败
    if data["warning"]:
        assert "超出" in data["warning"] or "未填写" in data["warning"]
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    assert len(entries) == data["entries"]
    for e in entries:
        assert e["work_date"] >= "2026-08-10", e
    # 排程规则默认不休息（AGV 现场常周末施工）：只断言日期不早于开始日
    from datetime import date
    assert all(date.fromisoformat(e["work_date"]) >= date(2026, 8, 10) for e in entries)


def test_schedule_split_totals_match_targets(client, pm_headers):
    """Sum of planned quantities across a task's entries == target quantity."""
    pid = _project_with_tasks(client, pm_headers)
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    from collections import defaultdict
    by_task = defaultdict(float)
    for e in entries:
        by_task[e["task_id"]] += e["planned_quantity"]

    # Compare with task tree targets
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree = r.json()
    task_targets = {}
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                task_targets[t["id"]] = t["target_quantity"]

    for tid, total in by_task.items():
        assert total == task_targets.get(tid), f"task {tid}: planned {total} != target {task_targets.get(tid)}"


def test_schedule_confirm_and_adjust(client, pm_headers):
    pid = _project_with_tasks(client, pm_headers)
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)

    # Adjust one entry: lock + change quantity
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = r.json()[0]
    r = client.put(f"/api/schedule/{entry['id']}", headers=pm_headers, json={
        "planned_quantity": 2,
        "is_locked": True,
        "notes": "现场确认后调整",
    })
    assert r.status_code == 200

    # Confirm
    r = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert r.status_code == 200
    assert r.json()["message"].startswith("已下达")

    # Verify changes persisted
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    updated = next(e for e in r.json() if e["id"] == entry["id"])
    assert updated["planned_quantity"] == 2
    assert updated["is_locked"] is True
    assert updated["is_confirmed"] is True


def test_replan_keeps_locked_entries(client, pm_headers):
    """Re-running generation keeps locked entries and rebuilds others."""
    pid = _project_with_tasks(client, pm_headers)
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    locked_id = entries[0]["id"]
    client.put(f"/api/schedule/{locked_id}", headers=pm_headers, json={"is_locked": True})

    # Replan
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200

    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    after = r.json()
    locked_ids = [e["id"] for e in after if e["is_locked"]]
    assert locked_id in locked_ids, "locked entry must survive replan"


# ===== 甘特拖拽：整任务平移（黑盒等价：逐条 PUT work_date）=====


def _shift_task(client, pm_headers, pid, task_id, days):
    """Shift all entries of a task by N days via the single-entry PUT."""
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    task_entries = [e for e in entries if e["task_id"] == task_id]
    assert task_entries, "task must have schedule entries"
    from datetime import date, timedelta
    for e in task_entries:
        new_date = (date.fromisoformat(e["work_date"]) + timedelta(days=days)).isoformat()
        r = client.put(f"/api/schedule/{e['id']}", headers=pm_headers, json={"work_date": new_date})
        assert r.status_code == 200, r.json()
    return task_entries


def test_shift_task_all_entries(client, pm_headers):
    pid = _project_with_tasks(client, pm_headers)
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    all_before = r.json()
    task_id = all_before[0]["task_id"]
    before = [e for e in all_before if e["task_id"] == task_id]

    _shift_task(client, pm_headers, pid, task_id, 3)

    # All entries of that task shifted by exactly +3 days
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    after_all = r.json()
    after = [e for e in after_all if e["task_id"] == task_id]
    assert len(after) == len(before)
    from datetime import date, timedelta
    for b, a in zip(before, after):
        assert a["work_date"] == (date.fromisoformat(b["work_date"]) + timedelta(days=3)).isoformat()
        # Other fields untouched (PUT only set work_date)
        assert a["planned_quantity"] == b["planned_quantity"]
        assert a["assignee_id"] == b["assignee_id"]
        assert a["status"] == b["status"]
    # Other tasks untouched
    before_others = {e["id"]: e["work_date"] for e in all_before if e["task_id"] != task_id}
    for e in after_all:
        if e["task_id"] != task_id:
            assert e["work_date"] == before_others[e["id"]]


def test_shift_into_weekend_allowed(client, pm_headers):
    """PUT work_date does not reject weekends (drag can cross weekends)."""
    pid = _project_with_tasks(client, pm_headers)
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = r.json()[0]

    # 排程本身已含周末；拖拽跨周末仍被允许
    from datetime import date
    assert date.fromisoformat(entry["work_date"]) <= date(2026, 8, 15)
    saturday = "2026-08-15"
    r = client.put(f"/api/schedule/{entry['id']}", headers=pm_headers, json={"work_date": saturday})
    assert r.status_code == 200, r.json()

    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    updated = next(e for e in r.json() if e["id"] == entry["id"])
    assert updated["work_date"] == saturday


def test_shift_task_with_locked_entry_still_allowed_by_api(client, pm_headers):
    """Locked entries can still be date-shifted via PUT (lock only guards replan)."""
    pid = _project_with_tasks(client, pm_headers)
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    task_id = entries[0]["task_id"]
    locked_id = entries[0]["id"]
    client.put(f"/api/schedule/{locked_id}", headers=pm_headers, json={"is_locked": True})

    _shift_task(client, pm_headers, pid, task_id, 2)

    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    locked = next(e for e in r.json() if e["id"] == locked_id)
    assert locked["is_locked"] is True
    from datetime import date, timedelta
    assert locked["work_date"] == (date.fromisoformat(entries[0]["work_date"]) + timedelta(days=2)).isoformat()


def test_rest_mode_two_skips_weekends(client, pm_headers):
    """休息两天（周六日）：排程不含周末。"""
    pid = _project_with_tasks(client, pm_headers)
    r = client.put(f"/api/projects/{pid}", headers=pm_headers, json={"rest_mode": "two"})
    assert r.status_code == 200, r.json()
    assert r.json()["rest_mode"] == "two"
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    from datetime import date
    assert len(r.json()) > 0
    for e in r.json():
        assert date.fromisoformat(e["work_date"]).weekday() < 5, e


def test_manual_rest_days_skipped_with_none_mode(client, pm_headers):
    """不休息模式下周末照常排程，但手动补充休息日始终跳过。"""
    pid = _project_with_tasks(client, pm_headers)
    r = client.put(f"/api/projects/{pid}", headers=pm_headers,
                   json={"rest_mode": "none", "rest_days": ["2026-08-15"]})
    assert r.status_code == 200
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    dates = {e["work_date"] for e in r.json()}
    assert "2026-08-15" not in dates
    # none=不休息：周六日照常排程
    from datetime import date
    assert any(date.fromisoformat(d).weekday() >= 5 for d in dates), "不休息模式下应包含周末"


def test_rest_mode_pattern_rejected(client, pm_headers):
    pid = _project_with_tasks(client, pm_headers)
    r = client.put(f"/api/projects/{pid}", headers=pm_headers, json={"rest_mode": "bogus"})
    assert r.status_code == 422


def test_holidays_skipped_when_enabled(client, pm_headers):
    """启用 skip_holidays 后法定节假日跳过；默认不跳过（现场赶工照常排）。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "节假日排程", "start_date": "2026-09-20", "new_vehicles": False, "end_date": "2026-10-20"})
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 50})
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": [f"mod-{i:02d}" for i in range(1, 9)]})
    assert r.status_code == 200
    # 默认不跳过节假日
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    assert "2026-10-01" in {e["work_date"] for e in r.json()}, "默认不跳过法定节假日"
    # 启用跳过 → 国庆假期全部跳过
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"skip_holidays": True})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    dates = {e["work_date"] for e in r.json()}
    for d in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07"):
        assert d not in dates, f"{d} 应被跳过"
    assert "2026-10-08" in dates
