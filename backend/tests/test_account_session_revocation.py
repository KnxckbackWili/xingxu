"""停用账号的旧会话撤销。"""

import pytest


@pytest.mark.parametrize("disable_method", ["put", "delete"])
def test_disabled_account_cannot_revive_old_sessions(client, admin_headers, disable_method):
    login = client.post("/api/auth/login", json={"username": "worker1", "password": "worker123"}).json()
    user_id = login["user"]["id"]
    old_headers = {"Authorization": f"Bearer {login['access_token']}"}
    if disable_method == "put":
        disabled = client.put(f"/api/users/{user_id}", headers=admin_headers, json={"is_active": False})
    else:
        disabled = client.delete(f"/api/users/{user_id}", headers=admin_headers)
    assert disabled.status_code == 200
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    assert client.put(f"/api/users/{user_id}", headers=admin_headers, json={"is_active": True}).status_code == 200
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    assert client.post("/api/auth/refresh", headers=old_headers,
                       json={"refresh_token": login["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "worker1", "password": "worker123"}).status_code == 200
