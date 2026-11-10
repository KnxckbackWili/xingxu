"""定时日报/周报：纯函数直接单测（不启动 APScheduler 线程）。"""

from tests.lifecycle_helpers import versioned
from tests.template_work import default_work
from datetime import date,datetime

from app import config
from app.db import SessionLocal
from app.services.report_scheduler import (
    generate_and_notify_weekly_report,
)


def _project(client, pm_headers, name="调度测试项目"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name,
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200
    pid=r.json()['id']
    from app.models import Project
    with SessionLocal() as db:
        db.get(Project,pid).created_at=datetime(2026,8,10);db.commit()
    return pid


def _project_with_work(client, pm_headers, worker_headers, name="调度测试项目"):
    """项目 + 车辆 + 工作项 + 一次真实现场检查登记，供周报断言。"""
    from tests.lifecycle_helpers import enter_execution
    from app.models import CheckItem
    pid = _project(client, pm_headers, name)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"work_item_ids": default_work("mod-01")})
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    enter_execution(client, pm_headers, pid)
    with SessionLocal() as db:
        check = db.query(CheckItem).filter_by(project_id=pid).first()
        cid, version = check.id, check.version or 0
    r = client.put(f"/api/projects/{pid}/check-items/{cid}", headers=worker_headers, json={"is_done": True, "version": version})
    assert r.status_code == 200, r.json()
    return pid


def _project_full_progress(client, pm_headers, worker_headers, name="调度测试项目"):
    """项目带车辆+工作项，现场实际全部完成（用于验收→完成→归档链路）。"""
    from tests.lifecycle_helpers import enter_execution, complete_all_work
    pid = _project(client, pm_headers, name)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"work_item_ids": default_work("mod-01")})
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    enter_execution(client, pm_headers, pid)
    complete_all_work(client, pm_headers, pid, recorder_headers=worker_headers)
    return pid


def _run_scheduled_weekly(db):
    return generate_and_notify_weekly_report(db, ref_date=date(2026, 8, 13))


def test_scheduled_weekly_report_notifies_pm(client, pm_headers, worker_headers):
    _project_with_work(client, pm_headers, worker_headers)

    db = SessionLocal()
    try:
        res = _run_scheduled_weekly(db)
        db.commit()
    finally:
        db.close()

    assert res["projects"] == 1
    assert res["notified"] == 1

    r = client.get("/api/notifications", headers=pm_headers)
    assert r.status_code == 200
    report_notifs = [n for n in r.json() if n["ntype"] == "report"]
    assert len(report_notifs) == 1
    assert "周报" in report_notifs[0]["title"]
    assert report_notifs[0]["is_read"] is False
    assert report_notifs[0]["project_id"] is not None

    # 审计记录（系统操作，无 operator）
    pid = r.json()[0]["project_id"]
    r = client.get(f"/api/projects/{pid}/logs", headers=pm_headers)
    report_logs = [l for l in r.json() if l["action"] == "report"]
    assert report_logs, "定时报告应写审计日志"
    assert report_logs[0]["operator_id"] is None


def test_weekly_report_on_monday_catches_latest_due_local_sunday(client, pm_headers):
    """重启于周一时接续刚到期的现场周日晚周期。"""
    _project(client, pm_headers)

    db = SessionLocal()
    try:
        res = generate_and_notify_weekly_report(db, now=datetime(2026, 8, 17,12))
        db.commit()
    finally:
        db.close()

    assert res['periods'][0]['period_key']=='2026-W33'
    assert res["period"] == "week"

    # 通知内容引用上一周周期
    r = client.get("/api/notifications", headers=pm_headers)
    weekly = [n for n in r.json() if "周报" in n["title"]]
    assert len(weekly) == 1
    assert "2026-08-10" in weekly[0]["content"]


def test_scheduler_skips_archived_but_reports_preparing(client, pm_headers, worker_headers):
    from tests.lifecycle_helpers import register_kickoff
    from tests.document_helpers import complete_documents
    pid = _project_full_progress(client, pm_headers, worker_headers)
    register_kickoff(client, pm_headers, pid)
    complete_documents(client, pm_headers, pid)
    assert client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "acceptance"}).status_code == 200
    signed = client.post(f"/api/projects/{pid}/acceptance", headers=pm_headers, json={
        "accepted_by_name": "客户验收代表", "accepted_at": "2026-09-30", "conclusion": "accepted"})
    assert signed.status_code == 200, signed.text
    for status, extra in (("completed", {}), ("archived", {"retrospective": "调度测试项目归档小结"})):
        r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": status, **extra})
        assert r.status_code == 200, r.text

    # A new project starts in preparing, which is active and does receive the weekly report.
    preparing = _project(client, pm_headers, '筹备项目也收到周报')
    assert client.get(f'/api/projects/{preparing}', headers=pm_headers).json()['status'] == 'preparing'

    db = SessionLocal()
    try:
        res = _run_scheduled_weekly(db)
        db.commit()
    finally:
        db.close()

    assert res["projects"] == 1
    reports = [n for n in client.get("/api/notifications", headers=pm_headers).json() if n["ntype"] == "report"]
    assert all(pid not in (n.get("link") or "") for n in reports)


def test_scheduler_skips_missing_pm(client, pm_headers, admin_headers):
    """manager 指向已停用/被移除用户 → 进 skipped 但仍生成。"""
    pid = _project(client, pm_headers)
    # 建一个临时负责人，指定后再停用（模拟负责人离职/账号停用；坏 ID 已被 C1-2 校验拦截）
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "temp_pm", "password": "pw123456",
        "display_name": "临时负责人", "role": "employee",
    })
    assert r.status_code == 200, r.text
    tmp_id = r.json()["id"]
    # Manager handover has its own audited route; model an account that later left directly.
    from app.models import Project
    from app.db import SessionLocal as Session
    with Session() as db:
        db.get(Project, pid).manager = tmp_id; db.commit()
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.get(User, tmp_id)
        u.is_active = False
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        res = _run_scheduled_weekly(db)
        db.commit()
    finally:
        db.close()

    assert res["projects"] == 0
    assert res["notified"] == 0
    assert res['skipped'][0]['project_id']==pid
    from app.models import ProjectReportReceipt
    with SessionLocal() as db:
        pending=db.query(ProjectReportReceipt).filter_by(project_id=pid).one()
        assert pending.delivery_pending and pending.delivered_at is None


def test_scheduler_flag_default_off():
    """守护约定：默认不启动调度线程（测试与本地开发安全）。"""
    assert config.SCHEDULER_ENABLED is False


# ===== 改造6：ISSUE_SLA_DAYS / ISSUE_SLA_TIME 环境变量化 =====
