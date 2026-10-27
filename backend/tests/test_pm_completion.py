"""HYPE-71 整改：项目经理/管理员可控制执行计划完成量（留痕审计）+ 修正通道。

覆盖范围：
1. pm/admin 直接填报 → 200，source=pm/admin、user_id=操作人、审计留痕。
2. 成员校验——非成员 worker 403；成员 worker 200（原行为不变）。
3. pm 离线 sync——reports 与 type=report 两条都接受 + 审计（无离线绕过差异）。
4. 车辆环节勾选/取消替换旧数量修正，见 test_vehicle_progress。
5. 停工拒绝填报；旧数据无 source 仍可读取。
7. /worker/records 与周期报告暴露 source。
"""

from tests.lifecycle_helpers import versioned
from app.time_utils import today_in

from app.db import SessionLocal
from app.models import DailyProgress


def _me(client, headers) -> str:
    return client.get("/api/auth/me", headers=headers).json()["id"]


def _setup_active(client, pm_headers, member_headers=None, name="PM完成量测试",
                  start_date="2026-08-10"):
    """建项目（5 台车，任务目标量充足）→ 生成任务+排程+确认 → 进入 executing。
    member_headers 非空时把该用户加入项目成员。"""
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "timezone": "Asia/Shanghai", "start_date": start_date, "end_date": "2026-12-31",
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
    if member_headers:
        uid = _me(client, member_headers)
        detail = client.get(f"/api/projects/{pid}", headers=pm_headers).json()
        r = client.put(f"/api/projects/{pid}", headers=pm_headers,
                       json=versioned(pid, {"members": [*detail["members"], uid]}))
        assert r.status_code == 200, r.json()
    return pid


def _entry(client, pm_headers, pid):
    entries = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()
    return next(e for e in entries if e["planned_quantity"] > 0)


def _dp(pid, client_uuid):
    with SessionLocal() as db:
        return db.query(DailyProgress).filter(
            DailyProgress.client_uuid == client_uuid).first()


def _audit_details(client, headers, pid) -> str:
    logs = client.get(f"/api/projects/{pid}/logs", headers=headers).json()
    return " | ".join(l.get("detail", "") for l in logs)


# ===================== pm/admin 直接填报 =====================

def test_pm_fill_200_source_pm_audit(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    entry = _entry(client, pm_headers, pid)
    pm_id = _me(client, pm_headers)

    r = client.post("/api/worker/reports", headers=pm_headers, json={
        "task_id": entry["task_id"], "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"], "completed_quantity": 2,
        "client_uuid": "pm-fill-0001"})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True

    dp = _dp(pid, "pm-fill-0001")
    assert dp is not None
    assert dp.source == "pm"
    assert dp.user_id == pm_id
    assert dp.completed_quantity == 2

    details = _audit_details(client, pm_headers, pid)
    assert "完成量填报（项目经理" in details
    assert "+2" in details


def test_admin_fill_200_source_admin_audit(client, admin_headers):
    pid = _setup_active(client, admin_headers)
    entry = _entry(client, admin_headers, pid)
    admin_id = _me(client, admin_headers)

    r = client.post("/api/worker/reports", headers=admin_headers, json={
        "task_id": entry["task_id"], "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"], "completed_quantity": 1,
        "client_uuid": "admin-fill-0001"})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True

    dp = _dp(pid, "admin-fill-0001")
    assert dp is not None
    assert dp.source == "admin"
    assert dp.user_id == admin_id

    details = _audit_details(client, admin_headers, pid)
    assert "完成量填报（管理员" in details
    assert "+1" in details


# ===================== 成员校验 =====================

def test_non_member_worker_404_member_worker_200(client, pm_headers, worker_headers):
    pid = _setup_active(client, pm_headers)  # worker1 未加入
    entry = _entry(client, pm_headers, pid)

    # 非成员不可见项目 → 404，不泄露项目存在性
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"], "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"], "completed_quantity": 1,
        "client_uuid": "worker-notmember-0001"})
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "项目不存在，或你不是项目成员且未获查看权限"

    # 加入成员后 → 200，source=worker，无管理审计
    uid = _me(client, worker_headers)
    detail = client.get(f"/api/projects/{pid}", headers=pm_headers).json()
    r = client.put(f"/api/projects/{pid}", headers=pm_headers,
                   json=versioned(pid, {"members": [*detail["members"], uid]}))
    assert r.status_code == 200, r.json()
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"], "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"], "completed_quantity": 1,
        "client_uuid": "worker-member-0001"})
    assert r.status_code == 200, r.text
    assert _dp(pid, "worker-member-0001").source == "worker"
    # worker 填报不产生「完成量填报」审计（避免噪音）
    assert "完成量填报（" not in _audit_details(client, pm_headers, pid)


# ===================== pm 离线 sync 两条都接受 =====================

def test_pm_sync_both_entries_accepted_with_audit(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    entry = _entry(client, pm_headers, pid)

    r = client.post("/api/worker/sync", headers=pm_headers, json={
        "reports": [{"task_id": entry["task_id"], "schedule_entry_id": entry["id"],
                     "work_date": entry["work_date"], "completed_quantity": 1,
                     "client_uuid": "pm-sync-a-0001"}]})
    assert r.status_code == 200
    assert r.json()["accepted"] == ["pm-sync-a-0001"], r.json()

    r = client.post("/api/worker/sync", headers=pm_headers, json={
        "ops": [{"type": "report", "client_uuid": "pm-sync-b-0001",
                 "payload": {"task_id": entry["task_id"], "schedule_entry_id": entry["id"],
                             "work_date": entry["work_date"], "completed_quantity": 1,
                             "client_uuid": "pm-sync-b-0001"}}]})
    assert r.status_code == 200
    assert r.json()["accepted"] == ["pm-sync-b-0001"], r.json()
    assert _dp(pid, "pm-sync-a-0001").source == "pm"
    assert _dp(pid, "pm-sync-b-0001").source == "pm"

    details = _audit_details(client, pm_headers, pid)
    assert details.count("完成量填报（项目经理") == 2


# ===================== 修正通道 =====================













def test_suspended_pm_fill_400(client, pm_headers):
    pid = _setup_active(client, pm_headers)
    entry = _entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers,
                    json={"status": "suspended", "reason": "现场停电，暂停施工"})
    assert r.status_code == 200, r.json()

    r = client.post("/api/worker/reports", headers=pm_headers, json={
        "task_id": entry["task_id"], "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"], "completed_quantity": 1,
        "client_uuid": "pm-suspend-fill-0001"})
    assert r.status_code == 400, r.text
    assert "不能再填报进度" in r.json()["detail"]




# ===================== 旧数据兼容 + 展示口径 =====================

def test_old_rows_without_source_read_as_worker(client, pm_headers, worker_headers):
    """旧数据：绕过 ORM 直插，source 列由迁移默认值补 'worker'，读取不报错。"""
    pid = _setup_active(client, pm_headers)
    entry = _entry(client, pm_headers, pid)
    worker_id = _me(client, worker_headers)
    task_id = entry["task_id"]

    from sqlalchemy import text
    with SessionLocal() as db:
        db.execute(text(
            "INSERT INTO daily_progress "
            "(id, project_id, task_id, work_date, user_id, completed_quantity, note, client_uuid, created_at) "
            "VALUES (:id, :pid, :tid, :wd, :uid, 1.5, '历史数据', 'old-row-0001', '2026-08-01')"
        ), {"id": "old-row-0001", "pid": pid, "tid": task_id, "wd": entry["work_date"], "uid": worker_id})
        db.commit()

    # /worker/records 读取正常且 source=worker（迁移默认值）
    r = client.get("/api/worker/records", headers=worker_headers)
    assert r.status_code == 200, r.text
    rec = next((x for x in r.json() if x["id"] == "old-row-0001"), None)
    assert rec is not None, r.json()
    assert rec["source"] == "worker"
    assert rec["completed_quantity"] == 1.5
