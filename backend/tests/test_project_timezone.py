"""P2-体验：项目级时区（俄/越现场）。

项目可配置 IANA 时区；"今日任务/撤回窗口"按项目现场时区取当地今天，
与服务器（默认上海）日历日可能相差一天。
"""
from tests.lifecycle_helpers import versioned


def _create_project(client, pm_headers, timezone="Asia/Shanghai", name="时区项目"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name,
        "start_date": "2026-08-10",
        "new_vehicles": False,
        "end_date": "2026-09-30",
        "timezone": timezone,
    })
    assert r.status_code == 200, r.json()
    return r.json()


def test_project_timezone_default_and_read(client, pm_headers):
    p = _create_project(client, pm_headers)
    assert p["timezone"] == "Asia/Shanghai"


def test_project_timezone_custom_and_update(client, pm_headers):
    p = _create_project(client, pm_headers, timezone="Europe/Moscow")
    assert p["timezone"] == "Europe/Moscow"
    # 可更新时区
    r = client.put(f"/api/projects/{p['id']}", headers=pm_headers, json=versioned(p['id'], {"timezone": "Asia/Ho_Chi_Minh"}))
    assert r.status_code == 200, r.json()
    assert r.json()["timezone"] == "Asia/Ho_Chi_Minh"


def test_project_invalid_timezone_rejected(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "非法时区项目", "start_date": "2026-08-10",
        "new_vehicles": False, "end_date": "2026-09-30",
        "timezone": "Mars/Olympus",
    })
    assert r.status_code == 400


