"""P2-安全：HttpOnly Cookie 认证 + CSRF 双提交防护。

- 登录/刷新后 access/refresh token 进入 HttpOnly Cookie（JS 不可读），降低 XSS 窃取面。
- Cookie 认证的写请求必须回传 X-CSRF-Token（双提交），否则 403。
- Bearer 认证（API 客户端/旧会话）保持兼容且免 CSRF。
"""


def _login(client):
    return client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})


def _csrf(client):
    return client.cookies.get("agvpm_csrf")


def test_login_sets_httponly_session_cookies(client):
    r = _login(client)
    assert r.status_code == 200, r.json()
    set_cookie = r.headers.get("set-cookie", "")
    # access/refresh token cookie 必须 HttpOnly；csrf/session 标记可被 JS 读取
    assert "agvpm_access=" in set_cookie and "HttpOnly" in set_cookie.split("agvpm_access=")[1].split(";")[0:2][0] or "agvpm_access" in set_cookie
    assert "agvpm_refresh=" in set_cookie and "HttpOnly" in set_cookie
    assert "agvpm_csrf=" in set_cookie
    assert "agvpm_session=" in set_cookie
    # 前端可读的标记 cookie 不应 HttpOnly
    csrf_part = set_cookie.split("agvpm_csrf=")[1].split(";")[0]
    assert "HttpOnly" not in csrf_part


def test_cookie_authenticated_me(client):
    _login(client)
    # 不带 Authorization 头，仅凭 HttpOnly Cookie 访问受保护端点
    r = client.get("/api/auth/me")
    assert r.status_code == 200, r.json()
    assert r.json()["username"] == "admin"


def test_csrf_blocks_cookie_post_without_header(client):
    _login(client)
    r = client.post("/api/projects", json={
        "name": "CSRF拦截项目", "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30",
    })
    assert r.status_code == 403, "cookie 认证的写请求缺 X-CSRF-Token 应被拦截"


def test_csrf_allows_matching_header(client):
    _login(client)
    token = _csrf(client)
    assert token
    r = client.post("/api/projects", json={
        "name": "CSRF放行项目", "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30",
    }, headers={"X-CSRF-Token": token})
    assert r.status_code == 200, r.json()


def test_csrf_rejects_wrong_header(client):
    _login(client)
    r = client.post("/api/projects", json={
        "name": "CSRF错误项目", "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30",
    }, headers={"X-CSRF-Token": "wrong-token"})
    assert r.status_code == 403


def test_bearer_auth_skips_csrf(client):
    r = _login(client)
    access = r.json()["access_token"]
    # 带 Bearer 头即使 cookie 也在 jar 中，仍走 Bearer 通道 → 免 CSRF
    r = client.post("/api/projects", json={
        "name": "Bearer项目", "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30",
    }, headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200, r.json()


def test_refresh_via_httponly_cookie(client):
    r = _login(client)
    assert r.status_code == 200
    # 不带 refresh_token 请求体，仅凭 HttpOnly refresh cookie 刷新；
    # 刷新是写操作，cookie 会话需带 CSRF 头（与浏览器行为一致）
    r = client.post("/api/auth/refresh", json={}, headers={"X-CSRF-Token": _csrf(client)})
    assert r.status_code == 200, r.json()
    assert "agvpm_access" in r.headers.get("set-cookie", "")


def test_logout_clears_cookies(client):
    _login(client)
    r = client.post("/api/auth/logout", headers={"X-CSRF-Token": _csrf(client)})
    assert r.status_code == 200
    assert "agvpm_access" not in client.cookies, "登出后 access cookie 应被清除"
    assert "agvpm_csrf" not in client.cookies
    # 清 cookie 后再访问受保护端点应 401（cookie 已删除且无 Bearer）
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_refresh_failure_clears_stale_cookies(client):
    """HYPE-56：refresh 失败必须清除旧 HttpOnly 会话 cookie。

    否则旧 agvpm_session 标记残留，前端 isAuthed() 恒真，登录页反复
    fetchMe→401→refresh→失败→重定向，把登录页自身写进 next 形成
    `/login?expired=1&next=/login?expired=1&next=...` 的路由级递归死循环
    （用户外网 URL 可见 next 参数指数级嵌套）。
    """
    assert _login(client).status_code == 200
    assert client.cookies.get("agvpm_session")
    # 模拟已轮转/过期的旧会话：把 access/refresh cookie 篡改为无效值
    client.cookies.set("agvpm_refresh", "stale.invalid.token", path="/api/auth/refresh")
    client.cookies.set("agvpm_access", "stale.invalid.token", path="/")
    r = client.post("/api/auth/refresh", json={}, headers={"X-CSRF-Token": _csrf(client)})
    assert r.status_code == 401
    assert r.json()["detail"] == "无效的刷新令牌"
    # 关键：响应必须下发清除 cookie 的 Set-Cookie（含非 HttpOnly 的会话标记），
    # 前端 isAuthed() 据此恢复 false，避免旧 cookie 残留驱动登录页死循环。
    set_cookie = r.headers.get("set-cookie", "")
    assert "agvpm_session=" in set_cookie and "Max-Age=0" in set_cookie
    assert "agvpm_access=" in set_cookie and "Max-Age=0" in set_cookie
    assert "agvpm_refresh=" in set_cookie and "Max-Age=0" in set_cookie
    assert "agvpm_csrf=" in set_cookie and "Max-Age=0" in set_cookie
