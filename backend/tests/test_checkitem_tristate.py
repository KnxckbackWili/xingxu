from tests.lifecycle_helpers import versioned
"""检查项三态（通过/不通过/不适用）测试。"""


def _project_with_check(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "三态项目", "start_date": "2026-09-01", "new_vehicles": False, "end_date": "2026-10-31"})
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-01"]})
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    ci = r.json()[0]["modules"][0]["tasks"][0]["check_items"][0]
    return pid, ci["id"]


def test_failed_requires_reason(client, pm_headers, worker_headers):
    pid, cid = _project_with_check(client, pm_headers)
    # worker 加为成员
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    # 不通过但不填原因 → 400
    r = client.put(f"/api/projects/{pid}/check-items/{cid}", headers=worker_headers, json={"failed": True})
    assert r.status_code == 400
    # 不通过 + 原因 → 200
    r = client.put(f"/api/projects/{pid}/check-items/{cid}", headers=worker_headers,
                   json={"failed": True, "failed_reason": "急停联动未响应"})
    assert r.status_code == 200
    assert r.json()["failed"] is True
    assert r.json()["failed_reason"] == "急停联动未响应"
    # tree 反映
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    t = r.json()[0]["modules"][0]["tasks"][0]
    ci = next(c for c in t["check_items"] if c["id"] == cid)
    assert ci["failed"] is True


def test_pass_clears_failed(client, pm_headers):
    pid, cid = _project_with_check(client, pm_headers)
    client.put(f"/api/projects/{pid}/check-items/{cid}", headers=pm_headers,
               json={"failed": True, "failed_reason": "x"})
    r = client.put(f"/api/projects/{pid}/check-items/{cid}", headers=pm_headers, json={"is_done": True})
    assert r.json()["is_done"] is True
    assert r.json()["failed"] is False
