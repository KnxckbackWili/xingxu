"""排程 AI 建议应用：按任务名匹配、保留锁定、下达新版本。"""


def _project(client, pm_headers):
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "AI 排程应用测试", "start_date": "2026-08-10", "end_date": "2026-09-30",
        "status": "planning",
    }).json()["id"]
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-01"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    return pid


def test_apply_ai_suggestions(client, pm_headers):
    pid = _project(client, pm_headers)
    schedule = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()
    assert schedule, "应有日程条目"
    target = schedule[0]
    r = client.post(f"/api/projects/{pid}/schedule/apply-suggestions", headers=pm_headers, json={
        "suggestions": [{"task_name": target["task_name"], "recommended_date": "2026-08-25"}],
        "confirm": True,
    })
    assert r.status_code == 200, r.text
    assert target["task_name"] in r.json()["applied"]
    assert r.json()["schedule_version"] == 1


def test_apply_suggestion_unknown_task(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/schedule/apply-suggestions", headers=pm_headers, json={
        "suggestions": [{"task_name": "不存在的任务"}],
        "confirm": True,
    })
    assert r.status_code == 200, r.text
    assert "不存在的任务" in r.json()["not_found"]
