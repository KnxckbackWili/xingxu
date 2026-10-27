"""Auth & RBAC tests."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["version"]


def test_login_success(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["user"]["role"] == "admin"


def test_refresh_token_uses_json_body(client):
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()
    r = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["access_token"]

    # Tokens in query strings leak into access logs and browser history.
    r = client.post(f"/api/auth/refresh?refresh={login['refresh_token']}")
    assert r.status_code == 422


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_me_requires_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_token(client, admin_headers):
    r = client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_worker_cannot_list_users(client, worker_headers):
    r = client.get("/api/users", headers=worker_headers)
    assert r.status_code == 403


def test_admin_can_list_users(client, admin_headers):
    r = client.get("/api/users", headers=admin_headers)
    assert r.status_code == 200
    usernames = [u["username"] for u in r.json()]
    assert "admin" in usernames and "worker1" in usernames


def test_pm_can_create_project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "PM 创建的项目",
        "start_date": "2026-09-01", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200


def test_worker_cannot_create_project(client, worker_headers):
    r = client.post("/api/projects", headers=worker_headers, json={
        "name": "越权项目",
        "start_date": "2026-09-01", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 403
