"""HYPE-88：个人临时日程 CRUD 与团队日程可见性（只读）。"""

from datetime import date, timedelta


def _auth(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _managed_project_with_entry(client, pm_headers, name="团队日程项目"):
    """PM 建项目（自己为经理）并生成一条排班指派给 worker。返回 (pid, entry)。"""
    today = date.today()
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name,
        "start_date": (today - timedelta(days=5)).isoformat(),
        "end_date": (today + timedelta(days=20)).isoformat(),
    })
    pid = r.json()["id"]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": ["user-worker-001"]})
    client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = r.json()[0]
    client.put(f"/api/schedule/{entry['id']}", headers=pm_headers,
               json={"assignee_id": "user-worker-001"})
    return pid, entry


# ===== A. 个人临时日程 =====

def test_personal_event_crud_roundtrip(client, pm_headers, worker_headers):
    """PM 创建/查/改/删本人临时日程；worker 角色一律 403；extra 字段 422。"""
    d1 = (date.today() + timedelta(days=1)).isoformat()
    # 归属项目（pm 自建 → 对自己可见）
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "临时日程归属项目",
        "start_date": (date.today() - timedelta(days=5)).isoformat(),
        "end_date": (date.today() + timedelta(days=5)).isoformat(),
    }).json()["id"]
    r = client.post("/api/dashboard/personal-events", headers=pm_headers, json={
        "project_id": pid, "work_date": d1, "title": "处理突发故障", "notes": "3 号仓"})
    assert r.status_code == 200, r.text
    eid = r.json()["event"]["id"]

    r = client.get("/api/dashboard/personal-events", headers=pm_headers)
    items = [e for e in r.json() if e["id"] == eid]
    assert items and items[0]["title"] == "处理突发故障" and items[0]["notes"] == "3 号仓"
    # HYPE-89：返回体含 project_id 与 project_name
    assert items[0]["project_id"] == pid and items[0]["project_name"] == "临时日程归属项目"

    r = client.put(f"/api/dashboard/personal-events/{eid}", headers=pm_headers, json={
        "project_id": pid, "work_date": (date.today() + timedelta(days=2)).isoformat(),
        "title": "处理突发故障（改期）", "notes": ""})
    assert r.status_code == 200 and r.json()["event"]["work_date"] == (date.today() + timedelta(days=2)).isoformat()

    # extra=forbid：不接受任何额外字段
    r = client.post("/api/dashboard/personal-events", headers=pm_headers, json={
        "project_id": pid, "work_date": d1, "title": "x", "notes": "", "user_id": "someone"})
    assert r.status_code == 422

    # worker/intern 不在 PM 端角色集 → 403（读写删都是）
    body = {"project_id": pid, "work_date": d1, "title": "x", "notes": ""}
    assert client.post("/api/dashboard/personal-events", headers=worker_headers, json=body).status_code == 403
    assert client.get("/api/dashboard/personal-events", headers=worker_headers).status_code == 403
    assert client.put(f"/api/dashboard/personal-events/{eid}", headers=worker_headers, json=body).status_code == 403
    assert client.delete(f"/api/dashboard/personal-events/{eid}", headers=worker_headers).status_code == 403

    r = client.delete(f"/api/dashboard/personal-events/{eid}", headers=pm_headers)
    assert r.status_code == 200
    r = client.get("/api/dashboard/personal-events", headers=pm_headers)
    assert all(e["id"] != eid for e in r.json())


def test_personal_event_other_user_entry_404(client, pm_headers, lead_headers, admin_headers):
    """他人条目与不存在条目统一 404（即使 admin 也不能动别人的）。"""
    d1 = (date.today() + timedelta(days=1)).isoformat()
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "他人条目项目",
        "start_date": (date.today() - timedelta(days=5)).isoformat(),
        "end_date": (date.today() + timedelta(days=5)).isoformat(),
    }).json()["id"]
    r = client.post("/api/dashboard/personal-events", headers=pm_headers, json={
        "project_id": pid, "work_date": d1, "title": "pm 的事项", "notes": ""})
    eid = r.json()["event"]["id"]

    for headers in (lead_headers, admin_headers):
        assert client.put(f"/api/dashboard/personal-events/{eid}", headers=headers, json={
            "project_id": "whatever", "work_date": d1, "title": "越权", "notes": ""}).status_code == 404
        assert client.delete(f"/api/dashboard/personal-events/{eid}", headers=headers).status_code == 404
        # 与不存在条目同一响应
        assert client.delete("/api/dashboard/personal-events/not-exist", headers=headers).status_code == 404
    # 本人仍可读
    assert any(e["id"] == eid for e in client.get("/api/dashboard/personal-events", headers=pm_headers).json())


def test_personal_event_project_binding_hype89(client, pm_headers, worker_headers, lead_headers):
    """HYPE-89：项目必填、不可见项目 404、PUT 允许改绑项目。"""
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "绑定项目A",
        "start_date": (date.today() - timedelta(days=5)).isoformat(),
        "end_date": (date.today() + timedelta(days=5)).isoformat(),
    }).json()["id"]
    pid_b = client.post("/api/projects", headers=pm_headers, json={
        "name": "绑定项目B",
        "start_date": (date.today() - timedelta(days=5)).isoformat(),
        "end_date": (date.today() + timedelta(days=5)).isoformat(),
    }).json()["id"]
    d1 = (date.today() + timedelta(days=1)).isoformat()

    # 缺 project_id → 422
    assert client.post("/api/dashboard/personal-events", headers=pm_headers, json={
        "work_date": d1, "title": "x", "notes": ""}).status_code == 422
    # 不可见项目（lead 非该项目经理/技术/协同）与不存在项目 → 404；worker 先被角色闸门 403
    body = {"project_id": pid, "work_date": d1, "title": "x", "notes": ""}
    assert client.post("/api/dashboard/personal-events", headers=worker_headers, json=body).status_code == 403
    assert client.post("/api/dashboard/personal-events", headers=lead_headers, json=body).status_code == 404
    assert client.post("/api/dashboard/personal-events", headers=pm_headers, json={
        **body, "project_id": "not-exist-project"}).status_code == 404

    r = client.post("/api/dashboard/personal-events", headers=pm_headers, json=body)
    eid = r.json()["event"]["id"]
    # PUT 改绑到项目 B，返回新项目名
    r = client.put(f"/api/dashboard/personal-events/{eid}", headers=pm_headers, json={
        **body, "project_id": pid_b})
    assert r.status_code == 200
    assert r.json()["event"]["project_id"] == pid_b
    assert r.json()["event"]["project_name"] == "绑定项目B"
    # 改绑：worker 先被角色闸门拦截（403）
    assert client.put(f"/api/dashboard/personal-events/{eid}", headers=worker_headers, json={
        **body, "project_id": pid_b}).status_code == 403


def test_personal_event_migration_backfill_path(client, pm_headers, upgrade_legacy_schema):
    """存量库补列路径：用「无 project_id 的旧表」模拟存量库，重跑幂等迁移后功能可用
    （新库路径由 Alembic 完整迁移链覆盖，即其余用例）。"""
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.db import engine

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE personal_events"))
        # 旧表结构：无 project_id 列（模拟 HYPE-88 首版的存量库）
        conn.execute(text("""
            CREATE TABLE personal_events (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                work_date DATE NOT NULL,
                title VARCHAR(100) NOT NULL,
                notes VARCHAR(500) DEFAULT '',
                created_at TIMESTAMP
            )
        """))
    upgrade_legacy_schema()

    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "补列路径项目",
        "start_date": (date.today() - timedelta(days=5)).isoformat(),
        "end_date": (date.today() + timedelta(days=5)).isoformat(),
    }).json()["id"]
    r = client.post("/api/dashboard/personal-events", headers=pm_headers, json={
        "project_id": pid, "work_date": (date.today() + timedelta(days=1)).isoformat(),
        "title": "补列后创建", "notes": ""})
    assert r.status_code == 200, r.text


# ===== B. 团队日程（只读） =====

def _create_pm_user(client, admin_headers, username, display_name):
    r = client.post("/api/users", headers=admin_headers, json={
        "username": username, "password": "Test1234!",
        "display_name": display_name, "role": "pm"})
    assert r.status_code == 200, r.text
    return _auth(client, username, "Test1234!")


def test_team_schedule_visibility_and_negative(client, admin_headers, pm_headers, worker_headers):
    """PM 只看自己管辖项目的人；仅作为他人项目普通成员的项目不计入；worker 403。"""
    from datetime import timedelta as td
    today = date.today()
    frm = (today - td(days=7)).isoformat()
    to = (today + td(days=30)).isoformat()

    # 甲（默认 pm 账号 user-pm-001）的管辖项目：worker 被排班
    pid_a, _ = _managed_project_with_entry(client, pm_headers, name="甲的项目")

    # 乙：另一个 PM 的项目，甲只是普通成员；乙项目里排班的是 worker2（若存在）或乙自己
    pm_b = _create_pm_user(client, admin_headers, "pm_b_hype88", "项目经理乙")
    pid_b, entry_b = _managed_project_with_entry(client, pm_b, name="乙的项目")
    # 甲加入乙项目作为普通成员（非经理/技术/协同）
    r = client.put(f"/api/projects/{pid_b}", headers=pm_b, json={"members": ["user-pm-001", "user-worker-001"]})
    assert r.status_code == 200, r.text
    # 乙项目排班指派给乙自己（保证乙项目有可被「看到」的人，若甲口径错误就会看到）
    client.put(f"/api/schedule/{entry_b['id']}", headers=pm_b,
               json={"assignee_id": "user-pm-001"})

    # 甲的团队日程：只见甲项目的人；乙项目条目（即便 assignee 是甲本人也不属于甲管辖项目）
    r = client.get(f"/api/dashboard/team-schedule?from={frm}&to={to}", headers=pm_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert all(e["project_id"] == pid_a for e in data["entries"])
    assert all(e["project_id"] != pid_b for e in data["entries"])
    people_ids = {p["id"] for p in data["people"]}
    assert "user-worker-001" in people_ids  # 甲项目被排班的人
    # 「项目经理乙」不是甲管辖项目里被排班/成员的人 → 甲看不到乙
    pm_b_id = next(u["id"] for u in client.get("/api/users/all-active", headers=admin_headers).json()
                   if u["display_name"] == "项目经理乙")
    assert pm_b_id not in people_ids

    # user_id 过滤：只留该人的条目
    r = client.get(f"/api/dashboard/team-schedule?from={frm}&to={to}&user_id=user-worker-001",
                   headers=pm_headers)
    assert all(e["assignee_id"] == "user-worker-001" for e in r.json()["entries"])

    # worker 403
    assert client.get(f"/api/dashboard/team-schedule?from={frm}&to={to}",
                      headers=worker_headers).status_code == 403


def test_team_schedule_admin_sees_all(client, admin_headers, pm_headers):
    """admin 可见全部用户/全部项目条目。"""
    _managed_project_with_entry(client, pm_headers, name="admin视野项目")
    today = date.today()
    frm = (today - timedelta(days=7)).isoformat()
    to = (today + timedelta(days=30)).isoformat()
    r = client.get(f"/api/dashboard/team-schedule?from={frm}&to={to}", headers=admin_headers)
    assert r.status_code == 200
    assert any(e["project_name"] == "admin视野项目" for e in r.json()["entries"])
