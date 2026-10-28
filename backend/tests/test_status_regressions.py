"""生命周期回归：相邻流转、验收门禁、生成工作不改状态、终态聚合口径（v3 六状态 + 突发停工）。"""
from tests.lifecycle_helpers import versioned, enter_execution, complete_all_work, register_kickoff


def _create(client, pm_headers, name, start="2026-08-10"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "start_date": start, "new_vehicles": False, "end_date": "2026-09-30"})
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    assert client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2}).status_code == 200
    assert client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-01"]}).status_code == 200
    return pid


def _status(client, headers, pid):
    return client.get(f"/api/projects/{pid}", headers=headers).json()["status"]


def _post(client, headers, pid, status, **extra):
    return client.post(f"/api/projects/{pid}/status", headers=headers, json={"status": status, **extra})


def _to_acceptance(client, pm_headers, pid, *, sign=True):
    """Real gates: on site, all work recorded, documents complete, signoffs → acceptance (+ customer signature)."""
    from tests.document_helpers import complete_documents
    enter_execution(client, pm_headers, pid)
    complete_all_work(client, pm_headers, pid)
    register_kickoff(client, pm_headers, pid)
    complete_documents(client, pm_headers, pid)
    assert _post(client, pm_headers, pid, "acceptance").status_code == 200
    if sign:
        r = client.post(f"/api/projects/{pid}/acceptance", headers=pm_headers, json={
            "accepted_by_name": "客户验收代表", "accepted_at": "2026-09-30", "conclusion": "accepted", "notes": "现场验收通过"})
        assert r.status_code == 200, r.text


def _finish(client, pm_headers, pid, target):
    _to_acceptance(client, pm_headers, pid)
    assert _post(client, pm_headers, pid, "completed").status_code == 200
    if target == "archived":
        assert _post(client, pm_headers, pid, "archived", retrospective="回归测试项目归档小结").status_code == 200
    assert _status(client, pm_headers, pid) == target


def test_strict_adjacent_flow_rejects_skips(client, pm_headers):
    """手动流转只允许相邻：准备不能直接跳到已完成，现场实施也不能跨阶段；原“待进场”已退役。"""
    pid = _create(client, pm_headers, "相邻流转项目")
    assert _status(client, pm_headers, pid) == "preparing"
    assert _post(client, pm_headers, pid, "executing").status_code == 400
    assert _post(client, pm_headers, pid, "completed").status_code == 400
    enter_execution(client, pm_headers, pid)
    assert _post(client, pm_headers, pid, "completed").status_code == 400
    assert _post(client, pm_headers, pid, "archived", retrospective="跳级").status_code == 400
    assert _post(client, pm_headers, pid, "ready").status_code == 400  # 已退役的状态
    assert _post(client, pm_headers, pid, "preparing").status_code == 200  # 相邻回退允许
    assert _status(client, pm_headers, pid) == "preparing"


def test_completed_projects_counts_completed_and_archived(client, pm_headers):
    """已统计口径：completed + archived 都计入，运营中不计入。"""
    _finish(client, pm_headers, _create(client, pm_headers, "已完成项目"), "completed")
    _finish(client, pm_headers, _create(client, pm_headers, "已归档项目"), "archived")
    enter_execution(client, pm_headers, _create(client, pm_headers, "执行中项目"))
    stats = client.get("/api/dashboard/overview", headers=pm_headers).json()["stats"]
    assert stats["total_projects"] == 3
    assert stats["completed_projects"] == 2
    assert stats["active_projects"] == 1


def test_overdue_uses_active_status_set(client, pm_headers):
    """逾期行动入口只统计运营中项目：已完成/已归档项目被排除。"""
    from datetime import datetime
    from app.db import SessionLocal
    from app.models import ProjectDocument
    pid_active = _create(client, pm_headers, "逾期运营中", start="2026-07-01")
    enter_execution(client, pm_headers, pid_active)
    with SessionLocal() as db:
        row = db.query(ProjectDocument).filter_by(project_id=pid_active, status="pending").first()
        row.due_at = datetime(2026, 7, 5); db.commit()
    pid_completed = _create(client, pm_headers, "已完成排除")
    _finish(client, pm_headers, pid_completed, "completed")
    pid_archived = _create(client, pm_headers, "已归档排除")
    _finish(client, pm_headers, pid_archived, "archived")
    r = client.get("/api/dashboard/overdue", headers=pm_headers)
    assert r.status_code == 200
    ids = {item["project_id"] for item in r.json()["projects"]}
    assert pid_active in ids
    assert pid_completed not in ids and pid_archived not in ids


def test_progress_write_preserves_human_selected_status(client, pm_headers):
    """即使进度写操作达到100%，也不改变人工选择的阶段。"""
    from unittest.mock import patch
    from app.db import SessionLocal
    from app.models import Project
    from app.services.status_flow import advance_project_status
    pid = _create(client, pm_headers, "单步推进项目")
    enter_execution(client, pm_headers, pid)
    complete_all_work(client, pm_headers, pid)
    assert _status(client, pm_headers, pid) == "executing"
    with SessionLocal() as db:
        p = db.get(Project, pid)
        with patch("app.services.progress.project_progress_tree", return_value={"percent": 100}):
            assert advance_project_status(db, p) is None
        db.commit()
    assert _status(client, pm_headers, pid) == "executing"
    logs = client.get(f"/api/projects/{pid}/logs", headers=pm_headers).json()
    assert not [log for log in logs if "自动切换状态" in log.get("detail", "")]


def test_acceptance_gate_blocks_completion_until_work_is_complete(client, pm_headers):
    """验收门禁：现场工作未全部完成时，人工确认进入已完成也会被拒绝。"""
    from app.db import SessionLocal
    from app.models import Task
    pid = _create(client, pm_headers, "验收门禁项目")
    _to_acceptance(client, pm_headers, pid)
    with SessionLocal() as db:
        task = db.query(Task).filter(Task.project_id == pid, Task.quantity_type != "per_vehicle").first()
        task.manually_completed = False; db.commit()
    r = _post(client, pm_headers, pid, "completed")
    assert r.status_code == 400, r.text
    assert _status(client, pm_headers, pid) == "acceptance"


def test_acceptance_gate_allows_completion_when_complete(client, pm_headers):
    pid = _create(client, pm_headers, "验收完成项目")
    _to_acceptance(client, pm_headers, pid)
    assert _post(client, pm_headers, pid, "completed").status_code == 200
    assert _status(client, pm_headers, pid) == "completed"


def test_preparing_preserved_after_task_generation(client, pm_headers):
    """生成工作不隐式改变项目状态。"""
    pid = _create(client, pm_headers, "保持筹备")
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-04"]})
    assert r.status_code == 200, r.json()
    assert _status(client, pm_headers, pid) == "preparing"
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"description": "生成后可编辑"})).status_code == 200
    assert _status(client, pm_headers, pid) == "preparing"
