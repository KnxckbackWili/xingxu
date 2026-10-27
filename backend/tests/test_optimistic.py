"""乐观锁：并发写冲突返回 409。"""


def _project(client, pm_headers):
    return client.post("/api/projects", headers=pm_headers, json={
        "name": "乐观锁测试", "start_date": "2026-08-10", "end_date": "2026-09-30",
    }).json()


def test_project_version_conflict(client, pm_headers):
    p = _project(client, pm_headers)
    assert "version" in p and p["version"] == 0
    # 用当前版本号更新 → 成功并自增
    r = client.put(f"/api/projects/{p['id']}", headers=pm_headers, json={"name": "改一次", "version": p["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1
    # 用过期版本号再更新 → 409
    r = client.put(f"/api/projects/{p['id']}", headers=pm_headers, json={"name": "再改", "version": p["version"]})
    assert r.status_code == 409, r.text


def test_project_update_without_version_ok(client, pm_headers):
    """旧前端不带 version 也能更新（向后兼容）。"""
    p = _project(client, pm_headers)
    r = client.put(f"/api/projects/{p['id']}", headers=pm_headers, json={"name": "兼容更新"})
    assert r.status_code == 200, r.text
    assert r.json()["version"] >= 1
