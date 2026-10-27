"""定时日报/周报：纯函数直接单测（不启动 APScheduler 线程）。"""

from tests.lifecycle_helpers import versioned
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
    """项目 + 车辆 + 任务 + 一次填报，供日报断言。"""
    pid = _project(client, pm_headers, name)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    # worker 加入项目后才能填报（成员校验）
    r = client.get("/api/auth/me", headers=worker_headers)
    wid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers,
               json=versioned(pid, {"members": [*r.json()["members"], wid]}))
    # 现场填报须先下达日程；本组测试关注日报/归档，而非未下达草稿。
    confirmed = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert confirmed.status_code == 200, confirmed.json()
    # worker 填报一条
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = r.json()[0]
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "project_id": pid, "task_id": entry["task_id"],
        "work_date": entry["work_date"], "completed_quantity": 1,
        "schedule_entry_id": entry["id"], "client_uuid": "test-report-scheduler-0001",
    })
    assert r.status_code == 200, r.json()
    return pid


def _project_full_progress(client, pm_headers, worker_headers, name="调度测试项目"):
    """项目带车辆+任务+日程且填报至 100% 进度（用于验收→完成→归档链路）。"""
    pid = _project(client, pm_headers, name)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get("/api/auth/me", headers=worker_headers)
    wid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers,
               json=versioned(pid, {"members": [*r.json()["members"], wid]}))
    # 现场填报须先下达日程；本组测试关注日报/归档，而非未下达草稿。
    confirmed = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert confirmed.status_code == 200, confirmed.json()
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    for i, e in enumerate(r.json()):
        r = client.post("/api/worker/reports", headers=worker_headers, json={
            "project_id": pid, "task_id": e["task_id"], "work_date": e["work_date"],
            "schedule_entry_id": e["id"], "completed_quantity": e["planned_quantity"],
            "client_uuid": f"test-report-scheduler-full-{i}",
        })
        assert r.status_code == 200, r.json()
    assert client.put(f'/api/projects/{pid}/events/internal_kickoff',headers=pm_headers,json={'actual_at':'2026-08-10T01:00:00Z'}).status_code==200
    from tests.document_helpers import complete_checks_and_documents
    complete_checks_and_documents(client, pm_headers, pid)
    # 沿相邻状态走到 ready（待进场），满足验收记录录入前提（C7-2 门禁要求 ready 之后）
    order = ["draft", "preparing", "planning", "ready"]
    cur = client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"]
    for st in order[order.index(cur) + 1:]:
        r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": st})
        assert r.status_code == 200, (st, r.json())
    # 验收签字记录（C7-2：completed/archived 门禁）
    r = client.post(f"/api/projects/{pid}/acceptance", headers=pm_headers, json={
        "accepted_by_name": "客户验收代表", "accepted_at": "2026-09-30",
        "conclusion": "accepted", "notes": "现场验收通过",
    })
    assert r.status_code == 200, r.json()
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


def test_scheduler_skips_archived_and_draft(client, pm_headers, worker_headers):
    pid = _project_full_progress(client, pm_headers, worker_headers)
    # 已由 helper 走到 ready；继续沿相邻状态走到归档（验收→完成需人工，完成→归档人工确认）
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    for status in ("executing", "commissioning", "pilot", "acceptance", "completed", "archived"):
        body = {"status": status}
        if status == "archived":
            body["retrospective"] = "调度测试项目归档小结"  # C8-3：归档需提交复盘小结
        r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json=body)
        assert r.status_code == 200

    # Keep the default-draft negative case real, rather than treating every
    # project made by this file's active-project helper as a draft.
    draft = client.post('/api/projects', headers=pm_headers, json={
        'name': '新建草稿不应收到定时报告', 'start_date': '2026-08-10', 'end_date': '2026-09-30',
    })
    assert draft.status_code == 200 and draft.json()['status'] == 'draft'

    db = SessionLocal()
    try:
        res = _run_scheduled_weekly(db)
        db.commit()
    finally:
        db.close()

    assert res["projects"] == 0
    assert res["notified"] == 0
    r = client.get("/api/notifications", headers=pm_headers)
    assert all(n["ntype"] != "report" for n in r.json())


def test_scheduler_skips_missing_pm(client, pm_headers, admin_headers):
    """manager 指向已停用/被移除用户 → 进 skipped 但仍生成。"""
    pid = _project(client, pm_headers)
    # 建一个临时负责人，指定后再停用（模拟负责人离职/账号停用；坏 ID 已被 C1-2 校验拦截）
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "temp_pm", "password": "pw123456",
        "display_name": "临时负责人", "role": "pm",
    })
    assert r.status_code == 200, r.text
    tmp_id = r.json()["id"]
    r = client.put(f"/api/projects/{pid}", headers=admin_headers, json=versioned(pid, {"manager_id": tmp_id}))
    assert r.status_code == 200, r.json()
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

def test_issue_sla_config_defaults():
    """默认 3 天 / 18:10，且已作为 config 属性暴露。"""
    assert config.ISSUE_SLA_DAYS == 3
    assert config.ISSUE_SLA_TIME == "18:10"


def test_issue_sla_config_validation():
    """非法输入回退默认（3 / 18:10），合法输入规范化。"""
    assert config._parse_sla_days(None) == 3
    assert config._parse_sla_days("abc") == 3
    assert config._parse_sla_days("0") == 3
    assert config._parse_sla_days("-2") == 3
    assert config._parse_sla_days("7") == 7
    assert config._parse_hhmm(None) == "18:10"
    assert config._parse_hhmm("") == "18:10"
    assert config._parse_hhmm("25:00") == "18:10"
    assert config._parse_hhmm("18:60") == "18:10"
    assert config._parse_hhmm("9:5") == "09:05"
    assert config._parse_hhmm("18:10") == "18:10"


def test_scan_overdue_uses_config_sla_hours(client, pm_headers, monkeypatch):
    """普通问题的经过小时阈值可配置，不再硬编码3天。"""
    from datetime import timedelta

    from app.db import SessionLocal
    from app.models import Issue
    from app.services.report_scheduler import scan_overdue_issues
    from app.time_utils import utcnow

    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "两天未解决问题", "severity": "medium",
    })
    issue_id = r.json()["id"]
    # 回拨到 2 天前：默认 3 天 SLA 不会命中，ISSUE_SLA_DAYS=1 时命中
    db = SessionLocal()
    try:
        i = db.get(Issue, issue_id)
        i.created_at = utcnow() - timedelta(days=2)
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(config, "ISSUE_SLA_DAYS", 1)
    monkeypatch.setattr(config, "ISSUE_SLA_NORMAL_HOURS", 24)
    db = SessionLocal()
    try:
        result = scan_overdue_issues(db)
        db.commit()  # 通知由调用方提交（与 _run_with_session 一致）
    finally:
        db.close()

    assert result["scanned"] >= 1
    msgs = client.get("/api/notifications", headers=pm_headers).json()
    sla_msgs = [n for n in msgs if "SLA 超时" in n["title"]]
    assert sla_msgs
    assert "已超过24小时" in sla_msgs[0]["content"]
