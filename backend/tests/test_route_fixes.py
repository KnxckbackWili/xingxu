"""Project overview answers 200 with its full response contract."""

import json
from datetime import date

from app.db import SessionLocal
from app.models import Task, User
from tests.template_work import default_work


CONTRACT_KEYS = ("progress", "timeline", "overdue", "issues", "tree", "logs", "preparations",
                 "weekly_plans", "document_progress", "document_actions", "project")


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

