"""生命周期回归：相邻流转、单步推进、验收门禁、初始状态保持、终态聚合口径。"""

_STATUS_ORDER = ["draft", "preparing", "planning", "ready", "executing",
                 "commissioning", "pilot", "acceptance", "completed", "archived"]


def _member(client, pm_headers, worker_headers, pid):
    r = client.get("/api/auth/me", headers=worker_headers)
    wid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers,
               json={"members": [*r.json()["members"], wid]})


def _create(client, pm_headers, name, status="planning", start="2026-08-10"):
    body = {"name": name, "start_date": start, "new_vehicles": False, "end_date": "2026-09-30"}
    if status:
        body["status"] = status
    r = client.post("/api/projects", headers=pm_headers, json=body)
    assert r.status_code == 200, r.json()
    return r.json()["id"]


def _walk_to(client, pm_headers, pid, target):
    """沿标准顺序逐级手动切换（只允许相邻，含验收→完成的人工门禁）。"""
    current = client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"]
    start = _STATUS_ORDER.index(current)
    end = _STATUS_ORDER.index(target)
    for status in _STATUS_ORDER[start + 1:end + 1]:
        if status == "executing":
            from tests.lifecycle_helpers import approve_risk_entry
            approve_risk_entry(client, pm_headers, pid)
        body = {"status": status}
        if status == "archived":
            body["retrospective"] = "回归测试项目归档小结"  # C8-3：归档需提交复盘小结
        r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json=body)
        assert r.status_code == 200, r.json()
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == target


def _full_progress_project(client, pm_headers, worker_headers, name="回归测试项目"):
    """创建项目 → 下达/填报 → 完成必需及安全检查 → 交付/验收/归档资料。

    数量达到目标不等于检查通过；用成员实际检查接口补齐质量条件，
    保留真实 completed/archived 门禁及原有聚合断言。
    """
    pid = _create(client, pm_headers, name)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    # Lifecycle aggregation tests need real issued work, not draft schedule reports.
    # Add the worker before generating so assignment sees the project member.
    _member(client, pm_headers, worker_headers, pid)
    generated = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert generated.status_code == 200, generated.json()
    confirmed = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert confirmed.status_code == 200, confirmed.json()
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    for i, e in enumerate(r.json()):
        r = client.post("/api/worker/reports", headers=worker_headers, json={
            "task_id": e["task_id"], "schedule_entry_id": e["id"],
            "work_date": e["work_date"], "completed_quantity": e["planned_quantity"],
            "client_uuid": f"reg-full-{pid[:6]}-{i}"})
        assert r.status_code == 200, r.json()
    from tests.document_helpers import complete_checks_and_documents
    complete_checks_and_documents(client, pm_headers, pid)
    # 走到 ready（待进场），满足验收记录录入前提（C7-2 门禁要求 ready 之后）
    _walk_to(client, pm_headers, pid, "ready")
    # 验收签字记录（C7-2：completed/archived 门禁）
    r = client.post(f"/api/projects/{pid}/acceptance", headers=pm_headers, json={
        "accepted_by_name": "客户验收代表", "accepted_at": "2026-09-30",
        "conclusion": "accepted", "notes": "现场验收通过",
    })
    assert r.status_code == 200, r.json()
    return pid


def test_strict_adjacent_flow_rejects_skips(client, pm_headers):
    """手动流转只允许相邻：不能跳级（planning → executing）或跨阶段回退。"""
    pid = _create(client, pm_headers, "相邻流转项目")
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "planning"
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 400
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "draft"})
    assert r.status_code == 400
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    assert r.status_code == 200
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "pilot"})
    assert r.status_code == 400


def test_completed_projects_counts_completed_and_archived(client, pm_headers, worker_headers):
    """已统计口径：completed + archived 都计入，运营中不计入。"""
    _walk_to(client, pm_headers, _full_progress_project(client, pm_headers, worker_headers, "已完成项目"), "completed")
    _walk_to(client, pm_headers, _full_progress_project(client, pm_headers, worker_headers, "已归档项目"), "archived")
    _walk_to(client, pm_headers, _full_progress_project(client, pm_headers, worker_headers, "执行中项目"), "executing")
    r = client.get("/api/dashboard/overview", headers=pm_headers)
    stats = r.json()["stats"]
    assert stats["total_projects"] == 3
    assert stats["completed_projects"] == 2
    assert stats["active_projects"] == 1


def test_overdue_uses_active_status_set(client, pm_headers, worker_headers):
    """逾期行动入口只统计运营中项目：已完成/已归档项目被排除。"""
    # 运营中项目（acceptance，未填）带逾期条目 → 应出现
    pid_active = _create(client, pm_headers, "逾期运营中", start="2026-07-01")
    client.post(f"/api/projects/{pid_active}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid_active}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid_active}/schedule/generate", headers=pm_headers)
    _walk_to(client, pm_headers, pid_active, "acceptance")
    # 已完成 / 已归档项目（进度 100%）→ 不应出现
    pid_completed = _full_progress_project(client, pm_headers, worker_headers, "已完成排除")
    _walk_to(client, pm_headers, pid_completed, "completed")
    pid_archived = _full_progress_project(client, pm_headers, worker_headers, "已归档排除")
    _walk_to(client, pm_headers, pid_archived, "archived")

    r = client.get("/api/dashboard/overdue", headers=pm_headers)
    assert r.status_code == 200
    ids = {item["project_id"] for item in r.json()["projects"]}
    assert pid_active in ids
    assert pid_completed not in ids
    assert pid_archived not in ids


def test_progress_write_preserves_human_selected_status(client, pm_headers, monkeypatch):
    """即使进度写操作达到100%，也不改变人工选择的阶段。"""
    pid = _create(client, pm_headers, "单步推进项目")
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    _walk_to(client, pm_headers, pid, "executing")

    from unittest.mock import patch
    from app.db import SessionLocal
    from app.models import Project
    from app.services.status_flow import advance_project_status
    db = SessionLocal()
    try:
        p = db.get(Project, pid)
        with patch("app.services.progress.project_progress_tree", return_value={"percent": 100}):
            new_status = advance_project_status(db, p)
        db.commit()
    finally:
        db.close()
    assert new_status is None
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "executing"
    # 没有阶段变更，不伪造自动切换审计
    logs = client.get(f"/api/projects/{pid}/logs", headers=pm_headers).json()
    auto = [log for log in logs if "自动切换状态" in log.get("detail", "")]
    assert len(auto) == 0


def test_acceptance_gate_blocks_completion_below_100(client, pm_headers):
    """验收门禁：进度不足 100% 时，人工确认进入已完成也会被拒绝。"""
    pid = _create(client, pm_headers, "验收门禁项目")
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    _walk_to(client, pm_headers, pid, "acceptance")
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "completed"})
    assert r.status_code == 400
    assert "100" in r.json()["detail"]["message"]
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "acceptance"


def test_acceptance_gate_allows_completion_at_100(client, pm_headers, worker_headers):
    """验收门禁：进度 100% 后人工确认可进入已完成。"""
    pid = _full_progress_project(client, pm_headers, worker_headers)
    _walk_to(client, pm_headers, pid, "acceptance")
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "completed"})
    assert r.status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "completed"


def test_draft_and_preparing_preserved_after_task_generation(client, pm_headers):
    """生成任务不再隐式改变项目状态：草稿/准备中等初始状态由用户选定后保持。"""
    for status in ("draft", "preparing"):
        pid = _create(client, pm_headers, f"保持状态-{status}", status=status)
        client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
            "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
        r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                        json={"module_ids": ["mod-03"]})
        assert r.status_code == 200, r.json()
        assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == status
