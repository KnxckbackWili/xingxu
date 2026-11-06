"""Vehicle issue source-of-truth and implementation co-manager coordination."""
from tests.lifecycle_helpers import versioned


def _project(client, pm_headers):
    response = client.post("/api/projects", headers=pm_headers, json={
        "name": "车辆问题协同项目", "start_date": "2026-08-01", "end_date": "2026-12-31",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]

