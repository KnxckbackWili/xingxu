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


def test_project_overview_200_with_contract(client, pm_headers):
    """有项目数据（任务+日程）时 GET overview 必须 200，且返回契约完整。"""
    pid = _project_with_schedule(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/overview", headers=pm_headers)
    assert r.status_code == 200, r.text

    body = r.json()
    # 聚合端点返回结构（routers/progress.project_overview 注释：progress/timeline/overdue/issues/tree/logs/preparations/schedule）
    for key in ("progress", "timeline", "overdue", "issues", "tree", "logs", "preparations", "schedule", "project"):
        assert key in body, f"overview 响应缺少契约键: {key}"

    # schedule 必须带稳定序号且按 work_date 升序（替代原 sort_order 列的兜底契约）
    schedule = body["schedule"]
    assert len(schedule) == 2, schedule
    dates = [item["work_date"] for item in schedule]
    assert dates == sorted(dates), f"schedule 未按 work_date 稳定排序: {dates}"
    for idx, item in enumerate(schedule):
        assert item["sort_order"] == idx, f"sort_order 应为稳定序号 {idx}: {item}"
        assert item["task_id"], item
        assert item["task_name"], item

    # completed_quantity 必须存在且按 DailyProgress 聚合（原 e.completed_quantity 同属缺失列）
    assert [item["completed_quantity"] for item in schedule] == [4, 0], [
        item["completed_quantity"] for item in schedule
    ]

    # overdue 聚合同样携带聚合后的 completed_quantity（两个过去日期条目都会命中）
    overdue_items = body["overdue"]["items"]
    assert len(overdue_items) == 2, overdue_items
    completed_by_id = {item["id"]: item["completed_quantity"] for item in overdue_items}
    assert set(completed_by_id.values()) == {4, 0}, completed_by_id

    assert body["project"]["id"] == pid
    assert body["project"]["name"] == "回归-进度总览"


def test_project_overview_200_empty_schedule(client, pm_headers):
    """即使没有日程条目，overview 也必须 200（空 schedule 数组 + 完整契约）。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "回归-空排程", "start_date": "2026-08-01", "new_vehicles": False, "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r = client.get(f"/api/projects/{pid}/overview", headers=pm_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schedule"] == []
    assert body["project"]["id"] == pid
