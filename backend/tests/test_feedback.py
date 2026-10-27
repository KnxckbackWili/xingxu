"""系统问题反馈（HYPE-72）：提交 / 字段校验 / 角色权限 / 列表分页筛选 / 详情 / 状态更新。

验收口径：
- 所有登录角色可提交；管理角色（admin/director/pm）可读取列表/详情并更新状态。
- 普通用户（worker/technician/lead）只能提交，读取与更新一律 403。
- 新表 feedback 由 init_db 的 create_all 幂等创建（建表 + 提交可用即证明迁移生效）。
"""


def _create(client, headers, description="系统页面加载慢", steps="反复刷新首页"):
    return client.post("/api/feedback", headers=headers,
                       json={"description": description, "steps": steps})


def _director_headers(client, admin_headers):
    """测试库内创建 director 角色并登录。"""
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "director1", "password": "Review123!",
        "display_name": "总监-测试", "role": "director"})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={"username": "director1", "password": "Review123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ===== 提交 =====

def test_worker_can_submit(client, worker_headers):
    r = _create(client, worker_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["description"] == "系统页面加载慢"
    assert data["steps"] == "反复刷新首页"
    assert data["status"] == "pending"
    assert data["user_name"] == "现场工程师A"  # worker1 display_name
    assert data["created_at"] is not None


def test_every_logged_in_role_can_submit(client, admin_headers, pm_headers, worker_headers, tech_headers, lead_headers):
    for idx, headers in enumerate((admin_headers, pm_headers, worker_headers, tech_headers, lead_headers)):
        r = _create(client, headers, description=f"来自角色-{idx}")
        assert r.status_code == 200, r.text
        assert r.json()["user_id"]  # 自动记录提交人


def test_anonymous_cannot_submit(client):
    assert client.post("/api/feedback", json={"description": "未登录提交"}).status_code == 401


# ===== 字段校验 =====

def test_validation_required_and_length_limits(client, worker_headers):
    # 空描述 → 422（pydantic min_length）
    assert client.post("/api/feedback", headers=worker_headers,
                       json={"description": ""}).status_code == 422
    # 纯空白描述 → 422（strip 后为空）
    assert client.post("/api/feedback", headers=worker_headers,
                       json={"description": "   "}).status_code == 422
    # 描述超长 → 422
    assert client.post("/api/feedback", headers=worker_headers,
                       json={"description": "x" * 2001}).status_code == 422
    # 复现步骤超长 → 422
    assert client.post("/api/feedback", headers=worker_headers,
                       json={"description": "ok", "steps": "s" * 5001}).status_code == 422
    # 未知字段 → 422（extra forbid）
    assert client.post("/api/feedback", headers=worker_headers,
                       json={"description": "ok", "extra": 1}).status_code == 422
    # 复现步骤可选：缺省可提交
    assert client.post("/api/feedback", headers=worker_headers,
                       json={"description": "只填描述"}).status_code == 200


# ===== 权限：普通角色只读接口一律 403 =====

def test_regular_roles_cannot_read_or_update(client, worker_headers, tech_headers, lead_headers):
    fb = _create(client, worker_headers).json()
    for headers in (worker_headers, tech_headers, lead_headers):
        assert client.get("/api/feedback", headers=headers).status_code == 403
        assert client.get(f"/api/feedback/{fb['id']}", headers=headers).status_code == 403
        assert client.patch(f"/api/feedback/{fb['id']}/status", headers=headers,
                            json={"status": "processing"}).status_code == 403


# ===== 权限：管理角色读取与更新 =====

def test_manage_roles_can_list_detail_and_update(client, admin_headers, pm_headers):
    fb = _create(client, admin_headers, description="管理角色读取测试").json()

    for headers in (admin_headers, pm_headers):
        lst = client.get("/api/feedback", headers=headers).json()
        assert lst["total"] == 1
        assert any(i["id"] == fb["id"] for i in lst["items"])

        det = client.get(f"/api/feedback/{fb['id']}", headers=headers)
        assert det.status_code == 200, det.text
        assert det.json()["description"] == "管理角色读取测试"
        assert det.json()["user_name"] == "系统管理员"

    # pm 可更新处理状态；非法状态被拦截
    r = client.patch(f"/api/feedback/{fb['id']}/status", headers=pm_headers, json={"status": "processing"})
    assert r.status_code == 200 and r.json()["status"] == "processing"
    r = client.patch(f"/api/feedback/{fb['id']}/status", headers=admin_headers, json={"status": "done"})
    assert r.json()["status"] == "done"


def test_director_is_manage_role(client, admin_headers, worker_headers):
    headers = _director_headers(client, admin_headers)
    fb = _create(client, worker_headers).json()

    assert client.get("/api/feedback", headers=headers).status_code == 200
    assert client.get(f"/api/feedback/{fb['id']}", headers=headers).status_code == 200
    assert client.patch(f"/api/feedback/{fb['id']}/status", headers=headers,
                        json={"status": "done"}).status_code == 200


# ===== 列表：分页 + 状态筛选 =====

def test_list_pagination_and_status_filter(client, admin_headers, worker_headers):
    for i in range(3):
        _create(client, worker_headers, description=f"问题{i}")
    lst = client.get("/api/feedback", headers=admin_headers).json()
    assert lst["total"] == 3
    fb = lst["items"][0]  # 最新在前
    client.patch(f"/api/feedback/{fb['id']}/status", headers=admin_headers, json={"status": "done"})

    page1 = client.get("/api/feedback?page=1&page_size=2", headers=admin_headers).json()
    assert page1["total"] == 3 and len(page1["items"]) == 2
    page2 = client.get("/api/feedback?page=2&page_size=2", headers=admin_headers).json()
    assert len(page2["items"]) == 1

    done = client.get("/api/feedback?status=done", headers=admin_headers).json()
    assert done["total"] == 1 and done["items"][0]["id"] == fb["id"]
    pending = client.get("/api/feedback?status=pending", headers=admin_headers).json()
    assert pending["total"] == 2


# ===== 非法状态与不存在 =====

def test_invalid_status_rejected(client, admin_headers, worker_headers):
    fb = _create(client, worker_headers).json()
    assert client.patch(f"/api/feedback/{fb['id']}/status", headers=admin_headers,
                        json={"status": "bogus"}).status_code == 422
    assert client.get("/api/feedback?status=bogus", headers=admin_headers).status_code == 422


def test_not_found(client, admin_headers):
    assert client.get("/api/feedback/does-not-exist", headers=admin_headers).status_code == 404
    assert client.patch("/api/feedback/does-not-exist/status", headers=admin_headers,
                        json={"status": "done"}).status_code == 404
