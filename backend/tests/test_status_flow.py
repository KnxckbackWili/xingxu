from tests.lifecycle_helpers import versioned
"""项目状态测试：日程下达到ready，执行阶段由授权人明确推进。"""


def _project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "状态自动推进项目",
        "status": "planning",  # This suite starts at the planning/issued boundary.
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    return r.json()["id"]


def _member(client, pm_headers, worker_headers, pid):
    r = client.get("/api/auth/me", headers=worker_headers)
    wid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers,
               json=versioned(pid, {"members": [*r.json()["members"], wid]}))


def _status(client, headers, pid):
    r = client.get(f"/api/projects/{pid}", headers=headers)
    return r.json()["status"]


def _fill_ratio(client, worker_headers, pid, ratio):
    """按比例填报全部日程：每条填 planned × ratio（支持小数，精确达成任务进度）。"""
    r = client.get(f"/api/projects/{pid}/schedule", headers=worker_headers)
    for i, e in enumerate(r.json()):
        qty = e["planned_quantity"] * ratio
        r = client.post("/api/worker/reports", headers=worker_headers, json={
            "task_id": e["task_id"], "schedule_entry_id": e["id"],
            "work_date": e["work_date"], "completed_quantity": qty,
            "client_uuid": f"status-flow-{pid[:6]}-{ratio}-{i}"})
        assert r.status_code == 200, r.json()


def _complete_quality_and_materials(client, pm_headers, pid):
    """Real-file material evidence plus required/safety checks for lifecycle gates."""
    from tests.document_helpers import complete_checks_and_documents
    complete_checks_and_documents(client, pm_headers, pid)


def _accept_project(client, pm_headers, pid):
    """录入验收签字记录（C7-2：completed 门禁要求存在 accepted 记录）。"""
    r = client.post(f"/api/projects/{pid}/acceptance", headers=pm_headers, json={
        "accepted_by_name": "客户验收代表",
        "accepted_at": "2026-09-30",
        "conclusion": "accepted",
        "notes": "现场验收通过",
    })
    assert r.status_code == 200, r.json()


def test_confirm_moves_planning_to_ready(client, pm_headers):
    # 日程下达表示计划已就绪，但不会越过人工进场确认直接开始实施。
    pid = _project(client, pm_headers)
    assert _status(client, pm_headers, pid) == "planning"
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert r.status_code == 200
    assert _status(client, pm_headers, pid) == "ready"


def test_progress_does_not_move_executing_to_pilot(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    _member(client, pm_headers, worker_headers, pid)
    # 车型 10 台 → mod-03 单车调试任务目标 10
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 10})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    assert client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"}).status_code == 200
    assert _status(client, pm_headers, pid) == "executing"
    # 每任务完成90%仍保持现场实施，进度不代替人工阶段确认
    _fill_ratio(client, worker_headers, pid, 0.9)
    assert _status(client, pm_headers, pid) == "executing"


def test_human_confirmation_completes_and_archives_at_100(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    _member(client, pm_headers, worker_headers, pid)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 10})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    assert client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"}).status_code == 200
    # 90%不会自动跳阶段
    _fill_ratio(client, worker_headers, pid, 0.9)
    assert _status(client, pm_headers, pid) == "executing"
    # 补齐剩余10%仍不跳阶段，随后负责人逐级确认
    _fill_ratio(client, worker_headers, pid, 0.1)
    assert _status(client, pm_headers, pid) == "executing"
    for stage in ("commissioning", "pilot", "acceptance"):
        response = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": stage})
        assert response.status_code == 200, response.text
    # 补齐交付物与归档清单（满足 completed/archived 门禁）
    _complete_quality_and_materials(client, pm_headers, pid)
    # 验收签字记录（C7-2 门禁）
    _accept_project(client, pm_headers, pid)
    # 验收 → 已完成 需人工确认且进度 100%
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "completed"})
    assert r.status_code == 200
    assert _status(client, pm_headers, pid) == "completed"
    # 已完成 → 已归档 仍由人工确认（C8-3：归档需提交复盘小结）
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers,
                    json={"status": "archived", "retrospective": "项目顺利收官，客户已验收"})
    assert r.status_code == 200
    assert _status(client, pm_headers, pid) == "archived"
