"""Vehicle issue source-of-truth and implementation co-manager coordination."""
from tests.lifecycle_helpers import versioned


def _project(client, pm_headers):
    response = client.post("/api/projects", headers=pm_headers, json={
        "name": "车辆问题协同项目", "start_date": "2026-08-01", "end_date": "2026-12-31",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_vehicle_issues_are_aggregated_without_copying_project_issues(client, pm_headers, worker_headers):
    project_id = _project(client, pm_headers)
    client.put(f"/api/projects/{project_id}", headers=pm_headers,
               json=versioned(project_id, {"members": ["user-worker-001"]}))
    unit_response = client.post(f"/api/projects/{project_id}/vehicle-units", headers=pm_headers, json={
        "asset_code": "AGV-007", "serial_number": "SN-007", "current_stage": "planned",
    })
    assert unit_response.status_code == 200, unit_response.text
    unit_id = unit_response.json()["id"]

    own_event = client.post(
        f"/api/projects/{project_id}/vehicle-units/{unit_id}/events",
        headers=worker_headers,
        json={
            "event_type": "fault", "event_date": "2026-08-12", "title": "驱动轮异响",
            "fault_part": "左驱动轮", "action_taken": "检查轴承并等待备件",
            "replaced_parts": [], "is_closed": False, "status_after": "fault",
        },
    )
    assert own_event.status_code == 200, own_event.text
    pm_event = client.post(
        f"/api/projects/{project_id}/vehicle-units/{unit_id}/events",
        headers=pm_headers,
        json={
            "event_type": "repair", "event_date": "2026-08-13", "title": "更换驱动轮轴承",
            "fault_part": "左驱动轮", "action_taken": "拆检并更换轴承",
            "replaced_parts": [{"name": "6204 轴承", "model": "6204-2RS", "quantity": 1}],
            "is_closed": False, "status_after": "fault",
        },
    )
    assert pm_event.status_code == 200, pm_event.text

    # 项目问题表保持独立，车辆记录仅在统一关注接口聚合展示。
    assert client.get(f"/api/projects/{project_id}/issues", headers=pm_headers).json() == []
    vehicle_rows = client.get(f"/api/projects/{project_id}/vehicle-issues", headers=pm_headers).json()
    assert len(vehicle_rows) == 2
    assert vehicle_rows[0]["replaced_parts"][0]["name"] == "6204 轴承"

    ordinary_focus = client.get("/api/dashboard/issues", headers=worker_headers).json()["items"]
    assert {item["title"] for item in ordinary_focus} == {"驱动轮异响"}

    grant = client.put(f"/api/projects/{project_id}", headers=pm_headers, json=versioned(project_id, {
        "co_managers": [{"user_id": "user-worker-001", "expires_at": "2099-12-31"}],
    }))
    assert grant.status_code == 200, grant.text
    co_manager_focus = client.get("/api/dashboard/issues", headers=worker_headers).json()["items"]
    assert {item["title"] for item in co_manager_focus} == {"驱动轮异响", "更换驱动轮轴承"}

    # 项目协管可以接手并关闭由其他人记录的车辆问题。
    closed = client.put(
        f"/api/projects/{project_id}/vehicle-units/{unit_id}/events/{pm_event.json()['id']}",
        headers=worker_headers,
        json={"is_closed": True, "status_after": "normal", "verification": "连续试运行正常"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["is_closed"] is True

    overview = client.get("/api/dashboard/overview", headers=pm_headers).json()
    row = next(item for item in overview["projects"] if item["id"] == project_id)
    assert row["open_issues"] == 1
