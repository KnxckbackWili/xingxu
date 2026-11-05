"""Issue 分类专属字段（extra）+ 通知补齐测试。"""
from tests.lifecycle_helpers import versioned


def _project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "问题分类测试项目",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    return r.json()["id"]


# ===== 分类可改 + 白名单 =====

def test_issue_type_updateable(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "车辆偏航", "issue_type": "hardware"})
    assert r.status_code == 200, r.json()
    iid = r.json()["id"]

    r = client.put(f"/api/issues/{iid}", headers=pm_headers, json=versioned(iid, {"issue_type": "software"}, 'Issue'))
    assert r.status_code == 200
    assert r.json()["issue_type"] == "software"


def test_issue_type_pattern_422(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "x", "issue_type": "bogus"})
    assert r.status_code == 422


def test_status_pattern_422(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={"title": "x"})
    iid = r.json()["id"]
    r = client.put(f"/api/issues/{iid}", headers=pm_headers, json=versioned(iid, {"status": "bogus"}, 'Issue'))
    assert r.status_code == 422


# ===== extra（分类专属字段）存取 =====

def test_issue_extra_roundtrip(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "充电桩故障",
        "issue_type": "hardware",
        "extra": {"device": "AGV-03", "affects_schedule": "影响"},
    })
    assert r.status_code == 200, r.json()
    assert r.json()["extra"] == {"device": "AGV-03", "affects_schedule": "影响"}

    # 更新 extra（整体覆盖）
    r = client.put(f"/api/issues/{r.json()['id']}", headers=pm_headers, json=versioned(r.json()['id'], {
        "extra": {"device": "AGV-03", "affects_schedule": "不影响"}}, 'Issue'))
    assert r.status_code == 200
    assert r.json()["extra"]["affects_schedule"] == "不影响"


def test_issue_extra_default_empty(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={"title": "无专属字段"})
    assert r.status_code == 200
    assert r.json()["extra"] == {}


# ===== 通知补齐 =====

def test_unassigned_issue_notifies_manager(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    # worker1 加入项目（上报需成员）
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    members = [*client.get(f"/api/projects/{pid}", headers=pm_headers).json()["members"], wid]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": members}))
    # worker 上报（不指定处理人）→ 项目负责人（pm）收到"新问题上报"
    r = client.post(f"/api/projects/{pid}/issues", headers=worker_headers, json={
        "title": "现场缺物料", "severity": "high"})
    assert r.status_code == 200

    r = client.get("/api/notifications", headers=pm_headers)
    notifs = r.json()
    assert any(n["title"].startswith("新问题上报") for n in notifs), notifs
    notice = next(n for n in notifs if n["title"].startswith("新问题上报"))
    assert notice["content"] == "严重程度：高 · 上报人：现场工程师A"


def test_unassigned_issue_no_self_notify(client, pm_headers):
    pid = _project(client, pm_headers)
    # pm 自己上报 → 自己是负责人，不打扰
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={"title": "自查问题"})
    assert r.status_code == 200

    r = client.get("/api/notifications", headers=pm_headers)
    assert all(not n["title"].startswith("新问题上报") for n in r.json())


def test_assignee_change_notifies_new_assignee(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    # Both assignees must be able to open the issue, not merely receive a notice.
    membership = client.put(f"/api/projects/{pid}", headers=pm_headers,
                            json=versioned(pid, {"members": ["user-worker-001", "user-worker-002"]}))
    assert membership.status_code == 200, membership.text
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "联调失败", "assignee_id": "user-worker-001"})
    assert r.status_code == 200
    iid = r.json()["id"]

    # 改派给 worker2 → worker2 收到指派通知（seed id: user-worker-002）
    r = client.put(f"/api/issues/{iid}", headers=pm_headers, json=versioned(iid, {"assignee_id": "user-worker-002"}, 'Issue'))
    assert r.status_code == 200

    r = client.post("/api/auth/login", json={"username": "worker2", "password": "worker123"})
    w2_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/api/notifications", headers=w2_headers)
    assert any(n["title"].startswith("新问题指派给你") for n in r.json())
    notice = next(n for n in r.json() if n["title"].startswith("新问题指派给你"))
    assert notice["content"] == "严重程度：中 · 上报人：项目经理"


# ===== 老库迁移：issues 表缺 extra 列 =====

