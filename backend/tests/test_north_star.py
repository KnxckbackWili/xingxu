"""P2-指标：北极星指标（试点）——已确认日程按计划执行率 OTE 的统计口径验证。"""

from datetime import date

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import DailyProgress, ScheduleEntry, Task, User


def _project_with_tasks(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "北极星指标试点项目", "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-01"]})
    assert r.status_code == 200, r.text
    return pid


def _insert_entry(db: Session, project_id: str, task_id: str, work_date: date,
                 planned_quantity: float, confirmed: bool = True) -> str:
    e = ScheduleEntry(
        project_id=project_id, task_id=task_id, work_date=work_date,
        planned_quantity=planned_quantity, is_confirmed=confirmed, status="planned",
    )
    db.add(e)
    db.flush()
    return e.id


def _insert_report(db: Session, project_id: str, task_id: str, entry_id: str,
                   work_date: date, completed_quantity: float, user_id: str) -> None:
    db.add(DailyProgress(
        project_id=project_id, task_id=task_id, schedule_entry_id=entry_id,
        work_date=work_date, user_id=user_id, completed_quantity=completed_quantity,
        client_uuid=f"ns-{entry_id[:8]}-{work_date}",
    ))
    db.flush()


def _seed(client, pm_headers):
    """构造基线+当期窗口数据；as_of 固定为 2026-09-15，观察窗 14 天。"""
    from app.db import SessionLocal
    pid = _project_with_tasks(client, pm_headers)
    db = SessionLocal()
    try:
        task_id = db.query(Task.id).filter(Task.project_id == pid).first()[0]
        user_id = db.query(User.id).filter(User.username == "pm").first()[0]
        as_of = date(2026, 9, 15)

        # ---- 基线窗口 [2026-08-05, 2026-09-01] ----
        be1 = _insert_entry(db, pid, task_id, date(2026, 8, 10), 10)
        _insert_report(db, pid, task_id, be1, date(2026, 8, 10), 10, user_id)  # 按期
        be2 = _insert_entry(db, pid, task_id, date(2026, 8, 11), 10)  # 无填报 → 未按期
        be3 = _insert_entry(db, pid, task_id, date(2026, 8, 20), 10)
        _insert_report(db, pid, task_id, be3, date(2026, 8, 25), 10, user_id)  # 晚于计划日 → 未按期

        # ---- 当期窗口 [2026-09-02, 2026-09-15] ----
        c1 = _insert_entry(db, pid, task_id, date(2026, 9, 2), 10)
        _insert_report(db, pid, task_id, c1, date(2026, 9, 2), 10, user_id)  # 按期
        c2 = _insert_entry(db, pid, task_id, date(2026, 9, 3), 10)
        _insert_report(db, pid, task_id, c2, date(2026, 9, 3), 5, user_id)
        _insert_report(db, pid, task_id, c2, date(2026, 9, 5), 5, user_id)  # 首次按期且量达标 → 按期
        c3 = _insert_entry(db, pid, task_id, date(2026, 9, 4), 10)
        _insert_report(db, pid, task_id, c3, date(2026, 9, 6), 10, user_id)  # 晚 → 未按期
        c4 = _insert_entry(db, pid, task_id, date(2026, 9, 10), 0)
        _insert_report(db, pid, task_id, c4, date(2026, 9, 10), 0, user_id)  # 无量纲，有填报即按期
        c5 = _insert_entry(db, pid, task_id, date(2026, 9, 11), 10)  # 无填报 → 未按期
        c6 = _insert_entry(db, pid, task_id, date(2026, 9, 12), 10)
        _insert_report(db, pid, task_id, c6, date(2026, 9, 12), 6, user_id)  # 量未达标 → 未按期
        db.commit()
        return pid, task_id, user_id, as_of
    finally:
        db.close()


def test_north_star_on_time_execution_rate(client, pm_headers):
    """当期 3/6=0.5，基线 1/3≈0.3333，delta≈0.1667。"""
    from app.services.north_star import compute_north_star

    pid, _task_id, _user_id, as_of = _seed(client, pm_headers)
    db = SessionLocal()
    try:
        result = compute_north_star(db, days=14, baseline_days=28, as_of=as_of)
        assert result["metric"] == "on_time_execution_rate"
        assert result["window"]["start"] == "2026-09-02"
        assert result["window"]["end"] == "2026-09-15"
        assert result["current"] == {"total": 6, "on_time": 3, "rate": 0.5}
        assert result["baseline"]["total"] == 3
        assert result["baseline"]["on_time"] == 1
        assert abs(result["baseline"]["rate"] - 0.3333) < 0.0001
        assert abs(result["delta"] - 0.1667) < 0.0001
        assert result["as_of"] == "2026-09-15"
    finally:
        db.close()


def test_north_star_empty_window_returns_none_rate(client, pm_headers):
    """无数据窗口：rate 为 None，delta 为 None（不产生除零）。"""
    from app.services.north_star import compute_north_star

    pid = _project_with_tasks(client, pm_headers)  # 无排程无填报
    db = SessionLocal()
    try:
        result = compute_north_star(db, days=14, baseline_days=28, as_of=date(2026, 9, 15))
        assert result["current"]["total"] == 0
        assert result["current"]["rate"] is None
        assert result["baseline"]["total"] == 0
        assert result["delta"] is None
        assert pid  # 项目存在但无已确认排程
    finally:
        db.close()


def test_north_star_http_endpoint(client, admin_headers):
    """HTTP 端点返回结构与鉴权。"""
    _seed(client, admin_headers)
    r = client.get("/api/north-star", headers=admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["metric"] == "on_time_execution_rate"
    assert "current" in data and "baseline" in data and "delta" in data
    assert data["window_days"] == 14

    r = client.get("/api/north-star", headers=admin_headers, params={"days": 7, "baseline_days": 14})
    assert r.status_code == 200
    assert r.json()["window_days"] == 7
    assert r.json()["baseline"]["window_days"] == 14
