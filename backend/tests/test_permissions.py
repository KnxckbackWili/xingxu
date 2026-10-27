"""Current seven-role permission matrix and project relation tests."""

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


def test_pm_and_worker_scope_is_explicit(client, admin_headers, pm_headers, worker_headers):
    other_pm = _user(client, admin_headers, "pm2", "pm")
    other = _project(client, admin_headers, "其他项目", manager_id=other_pm)
    assert client.get(f"/api/projects/{other}", headers=pm_headers).status_code == 404
    assert client.get(f"/api/projects/{other}/vehicles", headers=worker_headers).status_code == 404
    assert client.post(f"/api/projects/{other}/documents/files", headers=worker_headers,
                       files={"file": ("x.txt", b"x", "text/plain")}).status_code == 404


def test_designated_technical_manager_capabilities(client, admin_headers, pm_headers):
    lead_id = _user(client, admin_headers, "lead1", "lead")
    lead_headers = _login(client, "lead1")
    project_id = _project(client, pm_headers, "技术管理项目", technical_manager_id=lead_id)
    assert client.get(f"/api/projects/{project_id}", headers=lead_headers).status_code == 200
    generated = client.post(f"/api/projects/{project_id}/tasks/generate", headers=lead_headers,
                            json={"module_ids": ["mod-01"]})
    assert generated.status_code == 200, generated.text
    assert client.get(f"/api/projects/{project_id}/export/excel", headers=lead_headers).status_code == 200
    assert client.put(f"/api/projects/{project_id}", headers=lead_headers, json={"name": "越权"}).status_code == 403
    assert client.put(f"/api/projects/{project_id}", headers=lead_headers, json={"members": []}).status_code == 403
    assert client.delete(f"/api/projects/{project_id}", headers=lead_headers).status_code == 403


def test_ordinary_technician_is_read_only_until_designated(client, admin_headers, pm_headers):
    tech_id = _user(client, admin_headers, "tech1", "technician")
    tech_headers = _login(client, "tech1")
    project_id = _project(client, pm_headers, "技术项目")
    client.put(f"/api/projects/{project_id}", headers=pm_headers, json={"members": [tech_id]})
    assert client.get(f"/api/projects/{project_id}", headers=tech_headers).status_code == 200
    assert client.post(f"/api/projects/{project_id}/tasks/generate", headers=tech_headers,
                       json={"module_ids": ["mod-01"]}).status_code == 403
    client.put(f"/api/projects/{project_id}", headers=pm_headers, json={"technical_manager_id": tech_id})
    assert client.post(f"/api/projects/{project_id}/tasks/generate", headers=tech_headers,
                       json={"module_ids": ["mod-01"]}).status_code == 200


def test_director_sees_all_but_cannot_edit(client, admin_headers, pm_headers):
    _user(client, admin_headers, "director1", "director")
    headers = _login(client, "director1")
    project_id = _project(client, pm_headers, "总监可见项目")
    assert client.get(f"/api/projects/{project_id}", headers=headers).status_code == 200
    assert client.get(f"/api/projects/{project_id}/export/excel", headers=headers).status_code == 200
    assert client.put(f"/api/projects/{project_id}", headers=headers, json={"name": "越权"}).status_code == 403


def test_owner_and_admin_can_directly_delete_with_project_backup(client, admin_headers, pm_headers):
    project_id = _project(client, pm_headers, "负责人直接删除")
    assert client.delete(f"/api/projects/{project_id}", headers=pm_headers, params={"version": client.get(f"/api/projects/{project_id}", headers=pm_headers).json()["version"]}).status_code == 200
    assert client.get(f"/api/projects/{project_id}", headers=pm_headers).status_code == 404
    another = _project(client, pm_headers, "管理员直接删除")
    assert client.delete(f"/api/projects/{another}", headers=admin_headers, params={"version": client.get(f"/api/projects/{another}", headers=admin_headers).json()["version"]}).status_code == 200


def test_all_active_is_minimal(client, pm_headers, worker_headers):
    project_id = _project(client, pm_headers, "成员项目")
    client.put(f"/api/projects/{project_id}", headers=pm_headers, json={"members": ["user-worker-001"]})
    rows = client.get("/api/users/all-active", headers=worker_headers).json()
    assert {"user-worker-001", "user-pm-001"} <= {row["id"] for row in rows}
    assert all(key not in row for row in rows for key in ("username", "phone", "email"))


def test_documents_get_is_read_only(client, pm_headers):
    project_id = _project(client, pm_headers, "归档项目")
    first = client.get(f"/api/projects/{project_id}/documents", headers=pm_headers).json()["documents"]
    second = client.get(f"/api/projects/{project_id}/documents", headers=pm_headers).json()["documents"]
    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert all(row["status"] == "pending" and not row["versions"] for row in second)


def test_worker_project_co_manager_grant_is_scoped_and_expires(client, pm_headers, worker_headers):
    project_id = _project(client, pm_headers, "实施协管项目")
    grant = client.put(f"/api/projects/{project_id}", headers=pm_headers, json={
        "co_managers": [{"user_id": "user-worker-001", "expires_at": "2099-12-31"}],
    })
    assert grant.status_code == 200, grant.text

    detail = client.get(f"/api/projects/{project_id}", headers=worker_headers)
    assert detail.status_code == 200
    assert detail.json()["is_co_manager"] is True
    assert client.get("/api/auth/me", headers=worker_headers).json()["has_co_manager_projects"] is True
    assert client.put(f"/api/projects/{project_id}", headers=worker_headers,
                      json={"description": "由实施工程师协管"}).status_code == 200

    # 协管不能转移负责人，也不能继续委派其他协管。
    assert client.put(f"/api/projects/{project_id}", headers=worker_headers,
                      json={"manager_id": "user-worker-001"}).status_code == 403
    assert client.put(f"/api/projects/{project_id}", headers=worker_headers,
                      json={"co_managers": []}).status_code == 403

    expired = client.put(f"/api/projects/{project_id}", headers=pm_headers, json={
        "co_managers": [{"user_id": "user-worker-001", "expires_at": "2000-01-01"}],
    })
    assert expired.status_code == 200, expired.text
    assert client.get(f"/api/projects/{project_id}", headers=worker_headers).json()["is_co_manager"] is False
    assert client.get("/api/auth/me", headers=worker_headers).json()["has_co_manager_projects"] is False
    assert client.put(f"/api/projects/{project_id}", headers=worker_headers,
                      json={"description": "过期后不可管理"}).status_code == 403


def test_ai_drafts_require_matching_project_capability(client, pm_headers, worker_headers):
    project_id = _project(client, pm_headers, "AI 权限项目")
    client.put(f"/api/projects/{project_id}", headers=pm_headers, json={"members": ["user-worker-001"]})
    response = client.post("/api/ai-projects/organize/jobs", headers=worker_headers, json={
        "skill": "issues", "project_id": project_id, "source_text": "整理现场问题",
    })
    assert response.status_code == 403
    assert client.post("/api/ai-projects/organize/jobs", headers=worker_headers, json={
        "skill": "project", "source_text": "创建项目",
    }).status_code == 403
