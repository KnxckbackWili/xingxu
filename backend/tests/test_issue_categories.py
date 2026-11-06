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


# ===== 老库迁移：issues 表缺 extra 列 =====

