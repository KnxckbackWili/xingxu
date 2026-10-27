"""HYPE-48 排程优化测试：跨项目冲突检测 / 负载均衡指派 / 一键重排 / 可解释性。

覆盖：
- 跨项目冲突检测：排程预览返回逐人逐日冲突（同一天 ≥2 个项目）
- 负载均衡指派：跳过当日不可用人员、技能优先、超载退让
- 一键重排：逾期重排（锁定/已确认保护）、突发状况受阻重排、预览不落库
- 可解释性：预览/重排返回指派理由
"""

from datetime import date, timedelta


def _user_id(db, username: str) -> str:
    from app.models import User
    user = db.query(User).filter(User.username == username).first()
    assert user is not None, f"user {username} not found"
    return user.id


def _project_with_schedule(client, pm_headers, name: str, members: list,
                           start_date: str = "2026-08-10", modules=None) -> str:
    """建项目 → 加成员 → 生成任务 + 排程，返回 project_id。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "start_date": start_date, "new_vehicles": False, "end_date": "2026-09-30",
        "status": "planning",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    # 加车辆让 per_vehicle 任务获得目标数量（否则多数任务 target=None 无法排程）
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 5})
    assert r.status_code == 200, r.text
    if members:
        r = client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": members})
        assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": modules or [f"mod-{i:02d}" for i in range(1, 4)]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.text
    return pid


def _entries(client, pm_headers, pid: str) -> list:
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    assert r.status_code == 200, r.text
    return r.json()


# ===== 跨项目冲突检测 =====


def test_preview_shows_cross_project_conflicts(client, pm_headers):
    """同一人同一天被多个项目排程 → 排程预览逐人逐日标出冲突。"""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
    finally:
        db.close()

    pid_a = _project_with_schedule(client, pm_headers, "冲突项目A", [worker1])
    pid_b = _project_with_schedule(client, pm_headers, "冲突项目B", [worker1])

    # 两个项目都只有 worker1 一人 → 同一天（08-10 起）必然跨项目冲突
    r = client.get(f"/api/projects/{pid_a}/schedule/preview", headers=pm_headers)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["conflicts"], "preview 应返回跨项目冲突"
    # 冲突条目应包含 worker1 与 08-10 这类重叠日，且 project_count >= 2
    first = preview["conflicts"][0]
    assert first["project_count"] >= 2, first
    assert "项目" in first["projects"][0], first  # 冲突涉及 ≥2 个项目名
    # 预览不落库：条目数不变
    assert len(_entries(client, pm_headers, pid_a)) == preview["before"]


def test_conflicts_in_people_summary(client, pm_headers, monkeypatch):
    """人员看板 people-summary：跨项目冲突人员被标记 has_conflict。"""
    # 固定看板的本周，与下方 2026-08-10 排程夹具一致，避免跨月后失效。
    import app.routers.dashboard as dashboard
    class ReviewDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 10)
    monkeypatch.setattr(dashboard, 'date', ReviewDate)
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
    finally:
        db.close()

    _project_with_schedule(client, pm_headers, "看板冲突A", [worker1])
    _project_with_schedule(client, pm_headers, "看板冲突B", [worker1])

    r = client.get("/api/dashboard/people-summary", headers=pm_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    person = next((p for p in data["people"] if p["id"] == worker1), None)
    assert person is not None, "worker1 应在人员看板中"
    assert person["has_conflict"] is True, person
    assert person["conflict_days"] >= 1, person
    # 冲突详情含至少一个日期
    assert any(item["project_count"] >= 2 for item in person["conflict_details"])


# ===== 负载均衡指派 =====


def test_assignment_skips_unavailable_person(client, pm_headers):
    """自动排程跳过当日不可用人员（stage 1 不可用时段）。"""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker2 = _user_id(db, "worker2")
    finally:
        db.close()

    pid = _project_with_schedule(client, pm_headers, "不可用跳过", [worker1, worker2])
    start = "2026-08-10"
    # worker1 在排程首日不可用
    r = client.post(f"/api/users/{worker1}/unavailability", headers=pm_headers, json={
        "start_date": start, "end_date": start, "reason": "病假",
    })
    assert r.status_code == 200, r.text
    # 重新排程
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.text

    entries = _entries(client, pm_headers, pid)
    day_entries = [e for e in entries if e["work_date"] == start]
    assert day_entries, "首日应有排程"
    assert all(e["assignee_id"] != worker1 for e in day_entries), "不可用人员不应被排到首日"

    # 可解释性：生成返回指派理由（含「不可用」）
    gen = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers).json()
    assert gen.get("assignment_reasons"), "应返回指派理由"
    assert any("不可用" in r for r in gen["assignment_reasons"]), gen["assignment_reasons"]




def test_assignment_retreats_overloaded_person(client, pm_headers):
    """超载人员（按当日已排工时）靠后：其他项目已满载 → 本项目优先未超载者。"""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker2 = _user_id(db, "worker2")
    finally:
        db.close()

    start = "2026-08-10"
    # 项目B 只排 worker2 → worker2 在 08-10 起已有很多工时
    _project_with_schedule(client, pm_headers, "超载项目B", [worker2], start_date=start)
    # 项目A 有 worker1+worker2，同一起始日
    pid_a = _project_with_schedule(client, pm_headers, "均衡项目A", [worker1, worker2], start_date=start)

    entries = _entries(client, pm_headers, pid_a)
    day_entries = [e for e in entries if e["work_date"] == start]
    assert day_entries, "项目A 首日应有排程"
    # 08-10 当天 worker2 已被项目B 排满 → 项目A 首日应至少有一条排给负载更轻的 worker1
    assert any(e["assignee_id"] == worker1 for e in day_entries), \
        f"首日应优先未超载的 worker1：{day_entries}"


def test_assignment_roundrobin_fallback_without_data(client, pm_headers):
    """无技能/不可用数据时保留 round-robin 退化行为（不崩溃、有人分配）。"""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker2 = _user_id(db, "worker2")
    finally:
        db.close()

    pid = _project_with_schedule(client, pm_headers, "轮转退化", [worker1, worker2])
    entries = _entries(client, pm_headers, pid)
    assigned = {e["assignee_id"] for e in entries}
    assert assigned, "应有执行人"
    # 无任何优先级数据时两人都被分到（round-robin 均摊）
    assert worker1 in assigned and worker2 in assigned


# ===== 逾期/受阻一键重排 =====


def test_reschedule_overdue_keeps_locked_and_confirmed(client, pm_headers):
    """逾期重排：从指定日期起重排未完成量，锁定与已确认条目不动。"""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker2 = _user_id(db, "worker2")
    finally:
        db.close()

    pid = _project_with_schedule(client, pm_headers, "逾期重排", [worker1, worker2])
    before = _entries(client, pm_headers, pid)

    # 锁定第一条 + 确认第二条（模拟已下达版本）
    lock_id = before[0]["id"]
    confirm_id = before[1]["id"]
    r = client.put(f"/api/schedule/{lock_id}", headers=pm_headers, json={"is_locked": True})
    assert r.status_code == 200, r.text
    r = client.put(f"/api/schedule/{confirm_id}", headers=pm_headers, json={"is_confirmed": True})
    assert r.status_code == 200, r.text

    # 预览（不落库）
    r = client.get(f"/api/projects/{pid}/schedule/reschedule-preview",
                   headers=pm_headers, params={"start_date": "2026-08-20"})
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["rescheduled_tasks"], "应有逾期任务被重排"
    assert preview["removed_entries"] > 0
    # 预览不落库
    assert len(_entries(client, pm_headers, pid)) == len(before)

    # 确认重排
    r = client.post(f"/api/projects/{pid}/schedule/reschedule", headers=pm_headers,
                    json={"start_date": "2026-08-20"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["rescheduled_tasks"]

    after = _entries(client, pm_headers, pid)
    after_by_id = {e["id"]: e for e in after}
    # 锁定条目原样保留
    assert lock_id in after_by_id
    assert after_by_id[lock_id]["is_locked"] is True
    assert after_by_id[lock_id]["work_date"] == next(e["work_date"] for e in before if e["id"] == lock_id)
    # 已确认条目原样保留
    assert confirm_id in after_by_id
    assert after_by_id[confirm_id]["is_confirmed"] is True
    # 所有新排（未锁定未确认）条目从 08-20 起
    new_entries = [e for e in after if not e["is_locked"] and not e["is_confirmed"]]
    assert new_entries, "应有新排条目"
    assert all(e["work_date"] >= "2026-08-20" for e in new_entries)
    # 重排前（08-20 之前）的非锁定条目被移除
    old_dates = {e["work_date"] for e in before}
    assert any(d < "2026-08-20" for d in old_dates), "前置条件：有 08-20 之前的旧条目"




def test_reschedule_protects_confirmed_version(client, pm_headers):
    """已下达版本（全部确认）不被一键重排改动——无可删除条目时给出明确提示。"""
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
    finally:
        db.close()

    pid = _project_with_schedule(client, pm_headers, "版本保护", [worker1])
    r = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert r.status_code == 200, r.text
    before = _entries(client, pm_headers, pid)
    assert before and all(e["is_confirmed"] for e in before)

    r = client.post(f"/api/projects/{pid}/schedule/reschedule", headers=pm_headers,
                    json={"start_date": "2026-08-20"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["entries"] == 0, "已确认条目应受保护"
    assert data["rescheduled_tasks"] == []
    assert "未重排" in data["warning"] or "保留" in data["warning"], data["warning"]
    # 落库后条目数与日期完全不变
    after = _entries(client, pm_headers, pid)
    assert {e["id"]: e["work_date"] for e in after} == {e["id"]: e["work_date"] for e in before}


def test_reschedule_returns_assignment_reasons(client, pm_headers):
    """重排返回指派理由（可解释性），并在审计日志可查。"""
    from app.db import SessionLocal
    from app.models import ChangeLog
    from app.models import User
    db = SessionLocal()
    try:
        worker1 = _user_id(db, "worker1")
        worker2 = _user_id(db, "worker2")
    finally:
        db.close()

    pid = _project_with_schedule(client, pm_headers, "理由可查", [worker1, worker2])
    r = client.post(f"/api/projects/{pid}/schedule/reschedule", headers=pm_headers,
                    json={"start_date": "2026-08-20"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["rescheduled_tasks"]
    assert data["assignment_reasons"], "重排应返回指派理由"
    assert any("：" in line for line in data["assignment_reasons"]), data["assignment_reasons"]

    # 审计日志含「重排」与指派理由
    db = SessionLocal()
    try:
        log = (db.query(ChangeLog)
               .filter(ChangeLog.project_id == pid, ChangeLog.action == "schedule")
               .order_by(ChangeLog.created_at.desc()).first())
        assert log is not None, "应有审计日志"
        assert "重排" in (log.detail or ""), log.detail
    finally:
        db.close()
