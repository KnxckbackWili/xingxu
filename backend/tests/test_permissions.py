import pytest
"""Current seven-role permission matrix and project relation tests."""
from tests.lifecycle_helpers import versioned
from tests.template_work import default_work

PASSWORD = "pw123456"


def _user(client, admin_headers, username, role):
    response = client.post("/api/users", headers=admin_headers, json={
        "username": username, "password": PASSWORD, "display_name": username, "role": role,
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _project(client, headers, name, **extra):
    body = {"name": name, "start_date": "2026-08-01", "end_date": "2026-09-30", **extra}
    response = client.post("/api/projects", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_owner_and_admin_can_directly_delete_with_project_backup(client, admin_headers, pm_headers):
    project_id = _project(client, pm_headers, "负责人直接删除")
    assert client.delete(f"/api/projects/{project_id}", headers=pm_headers, params={"version": client.get(f"/api/projects/{project_id}", headers=pm_headers).json()["version"]}).status_code == 200
    assert client.get(f"/api/projects/{project_id}", headers=pm_headers).status_code == 404
    another = _project(client, pm_headers, "管理员直接删除")
    assert client.delete(f"/api/projects/{another}", headers=admin_headers, params={"version": client.get(f"/api/projects/{another}", headers=admin_headers).json()["version"]}).status_code == 200


def test_all_active_is_minimal(client, pm_headers, worker_headers):
    project_id = _project(client, pm_headers, "成员项目")
    rows = client.get("/api/users/all-active", headers=worker_headers).json()
    assert {"user-worker-001", "user-pm-001"} <= {row["id"] for row in rows}
    assert all(key not in row for row in rows for key in ("username", "phone", "email"))


def test_documents_get_is_read_only(client, pm_headers):
    project_id = _project(client, pm_headers, "归档项目")
    first = client.get(f"/api/projects/{project_id}/documents", headers=pm_headers).json()["documents"]
    second = client.get(f"/api/projects/{project_id}/documents", headers=pm_headers).json()["documents"]
    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert all(row["status"] == "pending" and not row["versions"] for row in second)

