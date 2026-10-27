"""Personnel management aggregation and large-roster coverage."""


def test_people_summary_handles_one_hundred_active_users(client, admin_headers):
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        schedulable_roles = ("lead", "pm", "technician", "worker", "intern")
        existing = db.query(User).filter(User.role.in_(schedulable_roles)).count()
        for index in range(100 - existing):
            db.add(User(
                username=f"capacity-user-{index:03d}",
                password_hash="not-used-in-this-test",
                display_name=f"容量测试人员{index + 1:03d}",
                role="worker",
                is_active=True,
            ))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/dashboard/people-summary", headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["active_people"] == 100
    assert data["summary"]["available_people"] == 100
    assert len(data["people"]) == 100
    assert sum(item["count"] for item in data["role_distribution"]) == 100

    pool_response = client.get("/api/dashboard/assignment-pool", headers=admin_headers)
    assert pool_response.status_code == 200, pool_response.text
    pool = pool_response.json()
    assert len(pool["items"]) == 100
    assert all("project_count" in item and "load_percent" in item for item in pool["items"])


def test_people_summary_role_distribution(client, admin_headers):
    """Role distribution matches active accounts; retired groups are absent."""
    response = client.get("/api/dashboard/people-summary", headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    role_total = sum(item["count"] for item in data["role_distribution"])
    assert role_total == data["summary"]["active_people"]
    assert "group_distribution" not in data


def test_overview_people_matches_summary(client, admin_headers):
    """HYPE-58：overview.people 与 people-summary 同一口径；列表不含项目名。"""
    summary = client.get("/api/dashboard/people-summary", headers=admin_headers).json()
    overview = client.get("/api/dashboard/overview", headers=admin_headers).json()
    people = overview["people"]
    assert people["summary"]["active_people"] == summary["summary"]["active_people"]
    assert people["summary"]["planned_hours"] == summary["summary"]["planned_hours"]
    assert people["summary"]["overloaded_people"] == summary["summary"]["overloaded_people"]
    for item in people["items"]:
        assert "projects" not in item
