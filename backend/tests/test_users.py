

def test_create_user_username_defaults_to_name(client, admin_headers):
    """登录用户名留空 → 自动用姓名。"""
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "", "password": "pw123456", "display_name": "张三", "role": "worker"})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "张三"
    # 用姓名登录
    r = client.post("/api/auth/login", json={"username": "张三", "password": "pw123456"})
    assert r.status_code == 200, r.text
    # 重名（姓名被占用）→ 400
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "", "password": "pw123456", "display_name": "张三", "role": "worker"})
    assert r.status_code == 400
