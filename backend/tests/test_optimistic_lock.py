"""P2-并发：乐观锁扩展到其余写端点。

已有：projects/tasks/issues/schedule_entries 的 PUT 主端点。
本次新增：
- check_items 增加 version 列，检查项 PUT 校验版本（现场多端同时打勾防覆盖）；
- 交付物子端点（POST tasks/{id}/deliverables）校验父任务版本，防提交/审核互相覆盖。
version 缺省（旧前端）时跳过校验但仍自增，保持向后兼容。
"""

import pytest


def _project_with_tree(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "乐观锁项目", "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.json()
    tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    return pid, tree


def _first_check_item(tree):
    for phase in tree:
        for mod in phase.get("modules", []):
            for t in mod.get("tasks", []):
                items = t.get("check_items") or []
                if items:
                    return t, items[0]
    return None, None


def _first_task(tree):
    for phase in tree:
        for mod in phase.get("modules", []):
            for t in mod.get("tasks", []):
                return t
    return None


def test_check_item_stale_version_409(client, pm_headers):
    """检查项：正确版本放行并自增；过期版本 409。"""
    pid, tree = _project_with_tree(client, pm_headers)
    task, ci = _first_check_item(tree)
    if task is None:
        pytest.skip("mod-03 未生成检查项，跳过")
    assert "version" in ci, "检查项序列化应包含 version"
    v0 = ci["version"]

    r = client.put(f"/api/projects/{pid}/check-items/{ci['id']}",
                   headers=pm_headers, json={"is_done": True, "version": v0})
    assert r.status_code == 200, r.json()

    # 用旧版本再写 → 409
    r = client.put(f"/api/projects/{pid}/check-items/{ci['id']}",
                   headers=pm_headers, json={"is_done": True, "version": v0})
    assert r.status_code == 409, r.json()

    # version 缺省（旧前端）：跳过校验但仍自增
    r = client.put(f"/api/projects/{pid}/check-items/{ci['id']}",
                   headers=pm_headers, json={"is_done": True})
    assert r.status_code == 200, r.json()


def test_document_state_stale_version_409(client, pm_headers):
    from tests.document_helpers import documents
    pid, _ = _project_with_tree(client, pm_headers)
    row = documents(client, pm_headers, pid)['documents'][0]
    path = f'/api/projects/{pid}/documents/{row["id"]}'
    payload = {'status': 'waived', 'reason': '客户明确不需要', 'version': row['version']}
    first = client.put(path, headers=pm_headers, json=payload)
    assert first.status_code == 200, first.text
    stale = client.put(path, headers=pm_headers, json=payload)
    assert stale.status_code == 409, stale.text
    current = client.get(f'/api/projects/{pid}/documents', headers=pm_headers).json()['documents']
    assert next(value for value in current if value['id'] == row['id'])['version'] == first.json()['version']
    omitted = client.put(path, headers=pm_headers, json={'status': 'pending', 'reason': '恢复资料要求'})
    assert omitted.status_code == 200, omitted.text
