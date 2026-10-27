"""HYPE-71「直接完成」：PM/admin 直接把任务标记为已完成（独立于填报量）。

覆盖范围：
1. pm/admin 完成 → 200，任务手动完成字段（完成人/角色/时间）落库 + 审计；
   不新建/修改 DailyProgress（真实完成量/历史/排程/单位保持不变）。
2. 无目标任务（target_quantity=None）同样可直接完成。
3. worker 403；已手动完成任务重复 complete 幂等 ignored。
4. reopen → 200，字段清空 + 审计；未手动完成 reopen 幂等 ignored。
5. 原因可选：无原因完成/重新打开 → 200（reason 落空串，审计不带原因）；旧客户端带原因兼容。
6. 项目已停工/已完成/已归档 → 400。
7. 完成影响项目计划进度（percent_map → project_progress_tree）；reopen 后恢复。
8. /projects/{id}/tree 暴露手动完成字段（含操作人姓名）。
"""

from app.db import SessionLocal
from app.models import Task, DailyProgress, Project


def _me(client, headers) -> str:
    return client.get("/api/auth/me", headers=headers).json()["id"]


def _setup_active(client, pm_headers, name="手动完成测试", start_date="2026-08-10"):
    """建项目（5 台车，任务目标量充足）→ 生成任务+排程+确认 → 进入 executing。"""
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "start_date": start_date, "end_date": "2026-12-31",
        "new_vehicles": False}).json()["id"]
    for stage in ("preparing", "planning"):
        started = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": stage})
        assert started.status_code == 200, started.text
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 5})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    confirmed = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert confirmed.status_code == 200, confirmed.text
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.json()
    return pid


def _first_task(client, headers, pid) -> dict:
    """返回 /tree 中的第一个执行任务（含 id/target_quantity/completed）。"""
    tree = client.get(f"/api/projects/{pid}/tree", headers=headers).json()
    for ph in tree:
        for m in ph["modules"]:
            if m["tasks"]:
                return m["tasks"][0]
    raise AssertionError("树中无任务")


def _audit_details(client, headers, pid) -> str:
    logs = client.get(f"/api/projects/{pid}/logs", headers=headers).json()
    return " | ".join(l.get("detail", "") for l in logs)


def _task_percent(client, headers, pid, task_id) -> float:
    tree = client.get(f"/api/projects/{pid}/progress", headers=headers).json()
    for ph in tree.get("phases", []):
        for m in ph.get("modules", []):
            for t in m.get("tasks", []):
                if t["id"] == task_id:
                    return t["percent"]
    raise AssertionError(f"任务 {task_id} 不在进度树中")


def _dp_count(task_id) -> int:
    with SessionLocal() as db:
        return db.query(DailyProgress).filter(DailyProgress.task_id == task_id).count()


# ===================== 完成 =====================

def test_pm_complete_200_fields_audit_no_fake_dp(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    pm_id = _me(client, pm_headers)
    dp_before = _dp_count(task["id"])

    r = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                    json={"reason": "现场验收通过，直接标记完成"})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True

    with SessionLocal() as db:
        t = db.get(Task, task["id"])
        assert t.manually_completed is True
        assert t.manual_completed_by == pm_id
        assert t.manual_completed_role == "pm"
        assert t.manual_completed_at is not None
        assert t.manual_completed_reason == "现场验收通过，直接标记完成"
        # 不伪造填报记录：DailyProgress 数量不变，目标数量/单位不变
        assert db.query(DailyProgress).filter(DailyProgress.task_id == task["id"]).count() == dp_before

    details = _audit_details(client, pm_headers, pid)
    assert "直接完成（项目经理" in details
    assert "标记为已完成" in details and "原因：现场验收通过，直接标记完成" in details


def test_admin_complete_200(client, admin_headers):
    pid = _setup_active(client, admin_headers)
    task = _first_task(client, admin_headers, pid)

    r = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=admin_headers,
                    json={"reason": "管理员复核确认完成"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        t = db.get(Task, task["id"])
        assert t.manually_completed is True and t.manual_completed_role == "admin"

    details = _audit_details(client, admin_headers, pid)
    assert "直接完成（管理员" in details


def test_worker_complete_403(client, pm_headers, worker_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    # Keep the project visible so this tests the capability gate, not scope hiding (404).
    response = client.put(f"/api/projects/{pid}", headers=pm_headers,
                          json={"members": ["user-worker-001"]})
    assert response.status_code == 200, response.text

    r = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=worker_headers,
                    json={"reason": "现场人员无权直接完成"})
    assert r.status_code == 403, r.text
    assert "项目角色无此能力" in r.json()["detail"] and "项目授权" in r.json()["detail"]


def test_complete_no_target_task(client, pm_headers):
    """无目标任务（target_quantity=None）也可直接完成。"""
    pid = _setup_active(client, pm_headers)
    tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    module_id = tree[0]["modules"][0]["id"]
    r = client.post(f"/api/projects/{pid}/tasks", headers=pm_headers, json={
        "module_id": module_id, "name": "无目标资料核对", "quantity_type": "manual",
        "target_quantity": None, "unit": "项"})
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    with SessionLocal() as db:
        assert db.get(Task, task_id).target_quantity is None

    r = client.post(f"/api/worker/tasks/{task_id}/complete", headers=pm_headers,
                    json={"reason": "资料已核对完毕，无需数量目标"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Task, task_id).manually_completed is True
    # 计划页可见手动完成标记
    tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    found = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["id"] == task_id:
                    found = t
    assert found is not None and found["manually_completed"] is True


def test_complete_no_target_no_reason_200(client, pm_headers):
    """用户主场景：旧项目补录任务无目标数量，直接完成且不填原因 → 200。"""
    pid = _setup_active(client, pm_headers)
    tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    module_id = tree[0]["modules"][0]["id"]
    r = client.post(f"/api/projects/{pid}/tasks", headers=pm_headers, json={
        "module_id": module_id, "name": "旧项目补录归档", "quantity_type": "manual",
        "target_quantity": None, "unit": "项"})
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    r = client.post(f"/api/worker/tasks/{task_id}/complete", headers=pm_headers, json={})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True
    with SessionLocal() as db:
        t = db.get(Task, task_id)
        assert t.manually_completed is True and t.manual_completed_reason == ""
    details = _audit_details(client, pm_headers, pid)
    assert "直接完成（项目经理" in details and "原因：" not in details


def test_already_completed_idempotent(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    r1 = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                     json={"reason": "第一次完成"})
    assert r1.status_code == 200 and r1.json()["accepted"] is True
    # 重复 complete：幂等忽略，不新增审计
    details_before = _audit_details(client, pm_headers, pid)
    r2 = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                     json={"reason": "重复提交"})
    assert r2.status_code == 200
    assert r2.json()["accepted"] is False
    assert _audit_details(client, pm_headers, pid) == details_before


def test_complete_no_reason_200(client, pm_headers):
    """原因可选：不填原因直接完成 → 200，reason 落空串，审计不带原因。"""
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    r = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                    json={})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True
    with SessionLocal() as db:
        t = db.get(Task, task["id"])
        assert t.manually_completed is True
        assert t.manual_completed_reason == ""
    details = _audit_details(client, pm_headers, pid)
    assert "直接完成（项目经理" in details and "标记为已完成" in details
    assert "原因：" not in details


# ===================== 重新打开 =====================

def test_reopen_200_clears_and_audit(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                json={"reason": "先完成"})
    pm_id = _me(client, pm_headers)

    r = client.post(f"/api/worker/tasks/{task['id']}/reopen", headers=pm_headers,
                    json={"reason": "发现遗漏，重新打开"})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True

    with SessionLocal() as db:
        t = db.get(Task, task["id"])
        assert t.manually_completed is False
        assert t.manual_completed_by is None
        assert t.manual_completed_role is None
        assert t.manual_completed_at is None
        assert t.manual_completed_reason == ""
        # 真实填报量不受影响
        assert db.query(DailyProgress).filter(DailyProgress.task_id == task["id"]).count() == 0

    details = _audit_details(client, pm_headers, pid)
    assert "重新打开（项目经理" in details
    assert "取消手动完成，恢复按实际完成量计算" in details and "原因：发现遗漏，重新打开" in details


def test_reopen_non_manual_idempotent(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    details_before = _audit_details(client, pm_headers, pid)
    r = client.post(f"/api/worker/tasks/{task['id']}/reopen", headers=pm_headers,
                    json={"reason": "本来就没完成"})
    assert r.status_code == 200
    assert r.json()["accepted"] is False
    assert _audit_details(client, pm_headers, pid) == details_before


def test_reopen_no_reason_200_clears_and_audit(client, pm_headers):
    """原因可选：无原因完成后再无原因重新打开 → 200，字段清空，审计不带原因。"""
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers, json={})
    assert _audit_details(client, pm_headers, pid) != ""  # 完成已留痕

    r = client.post(f"/api/worker/tasks/{task['id']}/reopen", headers=pm_headers, json={})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True
    with SessionLocal() as db:
        t = db.get(Task, task["id"])
        assert t.manually_completed is False
        assert t.manual_completed_by is None
        assert t.manual_completed_role is None
        assert t.manual_completed_at is None
        assert t.manual_completed_reason == ""
        assert db.query(DailyProgress).filter(DailyProgress.task_id == task["id"]).count() == 0
    details = _audit_details(client, pm_headers, pid)
    assert "重新打开（项目经理" in details and "取消手动完成，恢复按实际完成量计算" in details
    assert "原因：" not in details


# ===================== 项目状态守卫 =====================

def test_suspended_project_complete_400(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    client.post(f"/api/projects/{pid}/status", headers=pm_headers,
                json={"status": "suspended", "reason": "现场停电停工"})
    r = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                    json={"reason": "停工期间完成"})
    assert r.status_code == 400, r.text
    assert "不能操作" in r.json()["detail"] or "先恢复" in r.json()["detail"]


def test_terminal_project_complete_400(client, pm_headers):
    """已完成/已归档项目禁止直接完成（直接置状态，绕过复杂完成门禁）。"""
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = "completed"
        db.commit()
    r = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                    json={"reason": "已完成项目不应可操作"})
    assert r.status_code == 400, r.text

    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = "archived"
        db.commit()
    r = client.post(f"/api/worker/tasks/{task['id']}/reopen", headers=pm_headers,
                    json={"reason": "已归档项目不应可操作"})
    assert r.status_code == 400, r.text


# ===================== 进度与 100% 判定 =====================

def test_complete_affects_progress_and_reopen_restores(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    before = _task_percent(client, pm_headers, pid, task["id"])
    assert before < 100  # 无填报，按实际完成量计算 < 100%

    r = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                    json={"reason": "直接完成推高进度"})
    assert r.status_code == 200, r.text
    after = _task_percent(client, pm_headers, pid, task["id"])
    assert after == 100.0  # 手动完成 → 任务按 100% 计
    # 真实完成量不变
    tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["id"] == task["id"]:
                    assert t["completed"] == 0  # 未伪造完成量

    # 重新打开 → 恢复按实际完成量计算
    client.post(f"/api/worker/tasks/{task['id']}/reopen", headers=pm_headers,
                json={"reason": "撤回直接完成"})
    restored = _task_percent(client, pm_headers, pid, task["id"])
    assert restored == before


def test_tree_exposes_manual_fields(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    client.post(f"/api/worker/tasks/{task['id']}/complete", headers=pm_headers,
                json={"reason": "树接口暴露字段"})
    tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["id"] == task["id"]:
                    assert t["manually_completed"] is True
                    assert t["manual_completed_role"] == "pm"
                    assert t["manual_completed_by_name"] != ""
                    assert t["manual_completed_at"] is not None
                    assert t["manual_completed_reason"] == "树接口暴露字段"
                    return
    raise AssertionError("任务未在树中")
