"""HYPE-47 人员可用性（不可用时段）与技能标签测试。

覆盖：不可用时段 CRUD+权限+审计 / 分配冲突检测 / 看板统计 / 技能标签。
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient


def _user_id(db, username: str) -> str:
    from app.models import User
    user = db.query(User).filter(User.username == username).first()
    assert user is not None, f"user {username} not found"
    return user.id


def _worker2_headers(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "worker2", "password": "worker123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_project_with_schedule(client, pm_headers, name: str, worker_id: str) -> str:
    """建项目 → 加 worker 为成员 → 生成任务 + 排程，返回 project_id。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [worker_id]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": [f"mod-{i:02d}" for i in range(1, 4)]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.text
    return pid


def _first_entry(client, pm_headers, pid: str) -> dict:
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    assert r.status_code == 200, r.text
    assert r.json(), "expected schedule entries"
    return r.json()[0]


# ===== 不可用时段 CRUD + 权限 + 审计 =====


def test_unavailability_crud_and_permissions(client, admin_headers, pm_headers, worker_headers):
    from app.db import SessionLocal
    from app.models import User, ChangeLog

    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker2 = _user_id(db, "worker2")
    finally:
        db.close()

    # worker 无维护权限 → 403
    r = client.post(f"/api/users/{worker1}/unavailability", headers=worker_headers, json={
        "start_date": "2026-09-01", "end_date": "2026-09-03", "reason": "年假", "note": "陪家人",
    })
    assert r.status_code == 403, r.text

    # PM 登记
    r = client.post(f"/api/users/{worker1}/unavailability", headers=pm_headers, json={
        "start_date": "2026-09-01", "end_date": "2026-09-03", "reason": "年假", "note": "陪家人",
    })
    assert r.status_code == 200, r.text
    ua = r.json()
    assert ua["reason"] == "年假"
    assert ua["start_date"] == "2026-09-01" and ua["end_date"] == "2026-09-03"

    # 审计：写操作落 ChangeLog（org 级，project_id=None）
    db = SessionLocal()
    try:
        audit = (db.query(ChangeLog)
                 .filter(ChangeLog.entity_type == "user", ChangeLog.entity_id == worker1,
                         ChangeLog.action == "create", ChangeLog.project_id.is_(None))
                 .first())
        assert audit is not None, "expected audit log for unavailability create"
        assert "不可用" in (audit.detail or "")
    finally:
        db.close()

    # 本人可查看
    r = client.get(f"/api/users/{worker1}/unavailability", headers=worker_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    # 其他普通 worker 不可查看 → 403
    w2_headers = _worker2_headers(client)
    r = client.get(f"/api/users/{worker1}/unavailability", headers=w2_headers)
    assert r.status_code == 403, r.text

    # PM 修改
    r = client.put(f"/api/users/{worker1}/unavailability/{ua['id']}", headers=pm_headers, json={
        "end_date": "2026-09-05", "note": "延长",
    })
    assert r.status_code == 200, r.text
    assert r.json()["end_date"] == "2026-09-05"

    # 结束日期早于开始日期 → 400
    r = client.post(f"/api/users/{worker1}/unavailability", headers=pm_headers, json={
        "start_date": "2026-09-10", "end_date": "2026-09-05", "reason": "出差",
    })
    assert r.status_code == 400, r.text

    # PM 删除
    r = client.delete(f"/api/users/{worker1}/unavailability/{ua['id']}", headers=pm_headers)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/users/{worker1}/unavailability", headers=worker_headers)
    assert r.json() == []




# ===== 分配冲突检测（assignment-check） =====


def test_assignment_check_unavailable(client, pm_headers):
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker1_name = db.get(User, worker1).display_name
    finally:
        db.close()

    r = client.post(f"/api/users/{worker1}/unavailability", headers=pm_headers, json={
        "start_date": "2026-09-15", "end_date": "2026-09-15", "reason": "请假",
    })
    assert r.status_code == 200, r.text

    r = client.get("/api/schedule/assignment-check", headers=pm_headers,
                   params={"user_id": worker1, "work_date": "2026-09-15"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_available"] is False
    assert data["unavailable"]["reason"] == "请假"
    assert data["user_name"] == worker1_name

    # 非不可用日期 → 可用
    r = client.get("/api/schedule/assignment-check", headers=pm_headers,
                   params={"user_id": worker1, "work_date": "2026-09-20"})
    assert r.status_code == 200, r.text
    assert r.json()["is_available"] is True
    assert r.json()["unavailable"] is None


def test_assignment_check_cross_project_conflict(client, pm_headers):
    """同一天在其他可见项目已被排 → 汇总计数；排除当前项目后只算其他项目。"""
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
    finally:
        db.close()

    pid_a = _make_project_with_schedule(client, pm_headers, "冲突项目A", worker1)
    pid_b = _make_project_with_schedule(client, pm_headers, "冲突项目B", worker1)

    # 取两条排程条目，改成同一天同一执行人（确定性冲突）
    entry_a = _first_entry(client, pm_headers, pid_a)
    entry_b = _first_entry(client, pm_headers, pid_b)
    day = "2026-08-18"
    r = client.put(f"/api/schedule/{entry_a['id']}", headers=pm_headers, json={
        "assignee_id": worker1, "work_date": day})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/schedule/{entry_b['id']}", headers=pm_headers, json={
        "assignee_id": worker1, "work_date": day})
    assert r.status_code == 200, r.text

    # 排除 A → 只统计 B 的 1 条
    r = client.get("/api/schedule/assignment-check", headers=pm_headers,
                   params={"user_id": worker1, "work_date": day, "exclude_project_id": pid_a})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cross_project_total"] == 1, data
    assert data["cross_project_entries"][0]["project_name"] == "冲突项目B"

    # 不排除 → 两个项目各 1 条
    r = client.get("/api/schedule/assignment-check", headers=pm_headers,
                   params={"user_id": worker1, "work_date": day})
    data = r.json()
    assert data["cross_project_total"] == 2, data

    # 当前项目不可见时仍按可见范围统计（admin 可见全部）
    r = client.get("/api/schedule/assignment-check", headers=pm_headers,
                   params={"user_id": worker1, "work_date": day, "exclude_project_id": pid_a})


# ===== 人员看板统计 =====


def test_people_summary_unavailability(client, admin_headers):
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
    finally:
        db.close()

    today = date.today().isoformat()
    # 登记今天不可用 + 技能标签
    r = client.post(f"/api/users/{worker1}/unavailability", headers=admin_headers, json={
        "start_date": today, "end_date": today, "reason": "病假", "note": "调休"})
    assert r.status_code == 200, r.text


    r = client.get("/api/dashboard/people-summary", headers=admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    # 当前不可用人数 ≥1
    assert data["summary"]["unavailable_count"] >= 1
    # 近期不可用安排含该人员
    upcoming = data["summary"]["upcoming_unavailability"]
    assert any(item["user_id"] == worker1 and item["reason"] == "病假" for item in upcoming)
    # 人员行内带技能标签 + 不可用标记
    person = next(item for item in data["people"] if item["id"] == worker1)
    assert person["is_unavailable_today"] is True
    assert person["unavailable_period"]["reason"] == "病假"


# ===== 技能标签 =====
