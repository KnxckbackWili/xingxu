"""Internal AI token management and MCP endpoint tests."""


def test_admin_can_create_and_revoke_ai_token(client, admin_headers, pm_headers):
    r = client.post("/api/ai/internal/tokens", headers=pm_headers, json={
        "name": "不该成功",
        "user_id": "user-pm-001",
        "scopes": ["projects:read"],
    })
    assert r.status_code == 403

    r = client.post("/api/ai/internal/tokens", headers=admin_headers, json={
        "name": "Claude 只读",
        "user_id": "user-admin-001",
        "scopes": ["projects:read", "files:read"],
    })
    assert r.status_code == 200
    created = r.json()
    assert created["token"].startswith("agv_ai_")
    assert created["scopes"] == ["projects:read", "files:read"]

    listed = client.get("/api/ai/internal/tokens", headers=admin_headers).json()
    row = next(item for item in listed["items"] if item["id"] == created["id"])
    assert "token" not in row
    assert row["token_prefix"] == created["token"][:12]

    r = client.delete(f"/api/ai/internal/tokens/{created['id']}", headers=admin_headers)
    assert r.status_code == 200
    listed = client.get("/api/ai/internal/tokens", headers=admin_headers).json()
    row = next(item for item in listed["items"] if item["id"] == created["id"])
    assert row["is_active"] is False


def test_mcp_endpoint_rejects_missing_token(client):
    r = client.post("/api/ai/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 401


def test_mcp_tools_respect_identity_and_scopes(client):
    from app.services.ai_mcp import _mcp_scopes, _mcp_user_id, projects_list

    _mcp_user_id.set("user-admin-001")
    _mcp_scopes.set(["projects:read"])
    result = projects_list()
    assert '"ok": true' in result

    _mcp_scopes.set([])
    result = projects_list()
    assert '"ok": false' in result
