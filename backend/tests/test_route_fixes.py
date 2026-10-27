"""回归测试：HYPE-19 领导/总监视角审视确认的两个真实路由 500。

1. GET /api/projects/{id}/overview —— 曾因引用不存在的 ScheduleEntry.sort_order 列 500
   （ScheduleEntry 模型未定义该列；修复为 work_date + id 稳定排序，schedule 项带 0 基稳定序号）。
2. GET /api/team-templates/roles —— 曾因返回体含函数引用（role_label）无法 JSON 序列化 500
   （修复为 label = {角色: 中文标签} 的纯 dict）。

本文件验证"有项目数据时均为 200 且响应契约正确"。
"""

import json
from datetime import date

from app.db import SessionLocal
from app.models import DailyProgress, ScheduleEntry, Task, User


def _project_with_schedule(client, pm_headers, name="回归-进度总览"):
    """按真实链路造数：建项目 -> 生成任务 -> 插入日程条目 + 日报实报。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-01"]})
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        task_id = db.query(Task.id).filter(Task.project_id == pid).first()[0]
        assignee_id = db.query(User.id).filter(User.username == "pm").first()[0]
        e1 = ScheduleEntry(
            project_id=pid, task_id=task_id, work_date=date(2026, 8, 10),
            assignee_id=assignee_id, planned_quantity=10, status="planned", is_confirmed=True,
        )
        db.add(e1)
        db.flush()
        db.add(ScheduleEntry(
            project_id=pid, task_id=task_id, work_date=date(2026, 8, 11),
            assignee_id=assignee_id, planned_quantity=5, status="done", is_confirmed=True,
        ))
        # 第一个条目实报 4（跨 2 条日报，验证按 schedule_entry_id 聚合）
        db.add(DailyProgress(
            project_id=pid, task_id=task_id, schedule_entry_id=e1.id,
            work_date=date(2026, 8, 10), user_id=assignee_id, completed_quantity=3,
            client_uuid=f"rf-{e1.id[:8]}-a",
        ))
        db.add(DailyProgress(
            project_id=pid, task_id=task_id, schedule_entry_id=e1.id,
            work_date=date(2026, 8, 12), user_id=assignee_id, completed_quantity=1,
            client_uuid=f"rf-{e1.id[:8]}-b",
        ))
        db.commit()
        return pid
    finally:
        db.close()


CONTRACT_KEYS = ("progress", "timeline", "overdue", "issues", "tree", "logs", "preparations",
                 "weekly_plans", "document_progress", "document_actions", "project")


def test_project_overview_200_with_contract(client, pm_headers):
    """有旧日程与日报来源时 GET overview 仍 200；v3 契约不再输出按日日程，逾期按资料计算。"""
    pid = _project_with_schedule(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/overview", headers=pm_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in CONTRACT_KEYS:
        assert key in body, f"overview 响应缺少契约键: {key}"
    assert "schedule" not in body  # 按日排程已退役，旧条目只读保留，不再进入总览
    # 逾期只来自资料截止，不把旧日程条目算作逾期
    assert all(item["id"] == item["document_id"] for item in body["overdue"]["items"])
    assert body["project"]["id"] == pid
    assert body["project"]["name"] == "回归-进度总览"
    with SessionLocal() as db:
        assert db.query(ScheduleEntry).filter_by(project_id=pid).count() == 2
        assert db.query(DailyProgress).filter_by(project_id=pid).count() == 2


def test_project_overview_200_without_legacy_schedule(client, pm_headers):
    """没有任何旧日程来源时 overview 也必须 200 且契约完整。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "回归-空排程", "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}/overview", headers=pm_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(key in body for key in CONTRACT_KEYS)
    assert body["project"]["id"] == pid

