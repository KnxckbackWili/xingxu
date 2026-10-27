"""Template + task generation tests."""
from tests.lifecycle_helpers import versioned


def _new_project(client, pm_headers, name="任务生成测试项目"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name,
        "client": "测试客户",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200
    return r.json()["id"]


def test_template_tree_has_seed_content(client, pm_headers):
    r = client.get("/api/templates/default/tree", headers=pm_headers)
    assert r.status_code == 200
    phases = r.json()
    # C2-2：模板树完整返回 9 阶段（含「项目准备」），编辑器不再排除
    assert len(phases) == 9
    assert any(p["name"] == "项目准备" for p in phases)
    # 单车调试阶段按名称查找，避免依赖排序。
    phase3 = next(p for p in phases if p["name"] == "单车调试")
    assert any(m["name"] == "单车调试" for m in phase3["modules"])
    # 单车调试 module has 5 tasks, first with check items
    mod = next(m for m in phase3["modules"] if m["name"] == "单车调试")
    assert len(mod["tasks"]) == 5
    assert len(mod["tasks"][0]["check_items"]) >= 3

    survey = next(
        t for phase in phases for module in phase["modules"] for t in module["tasks"]
        if t["name"] == "场地勘测"
    )
    assert 'deliverables' not in survey
    requirements = client.get('/api/templates/default/document-requirements', headers=pm_headers).json()
    assert len([row for row in requirements if not row['is_group'] and row['stage_key'] != 'legacy']) == 53
    assert survey["ref_docs"][0]["filename"] == "现场勘测检查要点.txt"


def test_template_has_extra_modules(client, pm_headers):
    r = client.get("/api/templates/default/tree", headers=pm_headers)
    phases = r.json()
    all_mods = [m for ph in phases for m in ph["modules"]]
    names = [m["name"] for m in all_mods]
    for extra in ["相机", "二维码扫描", "自动门", "电梯", "PLC", "PDA", "自动充电"]:
        assert extra in names, f"缺少附加模块: {extra}"


def test_generate_tasks_with_vehicles(client, pm_headers):
    """per_vehicle tasks get target = sum of vehicle quantities."""
    project_id = _new_project(client, pm_headers)
    # Add vehicles first
    client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 5})
    client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "堆高车", "model_name": "Fork-1000", "quantity": 3})

    # Generate with core modules only (ids mod-01..mod-08)
    core_ids = [f"mod-{i:02d}" for i in range(1, 9)]
    r = client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                    json={"module_ids": core_ids})
    assert r.status_code == 200, r.json()
    data = r.json()
    assert data["tasks"] > 20

    # Task tree
    r = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    assert r.status_code == 200
    tree = r.json()
    assert len(tree) == 8

    # Find 开箱检查 (per_vehicle, should be 8 = 5+3)
    opening = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "开箱检查":
                    opening = t
    assert opening is not None
    assert opening["target_quantity"] == 8
    assert opening["quantity_type"] == "per_vehicle"

    # 服务器部署 fixed → target 1
    server_task = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "服务器部署与配置":
                    server_task = t
    assert server_task is not None
    assert server_task["target_quantity"] == 1

    # 连续运行监控 fixed 7
    trial = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "连续运行监控":
                    trial = t
    assert trial is not None
    assert trial["target_quantity"] == 7


def test_project_preparation_is_reminder_only(client, pm_headers):
    project_id = _new_project(client, pm_headers, "准备提醒隔离测试")
    r = client.post(
        f"/api/projects/{project_id}/tasks/generate",
        headers=pm_headers,
        json={"module_ids": ["mod-16", "mod-01"]},
    )
    assert r.status_code == 200, r.json()

    tree = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers).json()
    assert all(phase["name"] != "项目准备" for phase in tree)

    schedule = client.post(f"/api/projects/{project_id}/schedule/generate", headers=pm_headers)
    assert schedule.status_code == 200, schedule.json()
    assert all(task["name"] != "项目实施范围冻结" for task in schedule.json()["tasks"])

    preparations = client.get(f"/api/projects/{project_id}/procurements", headers=pm_headers)
    assert preparations.status_code == 200
    assert preparations.json()['items'] == []


def test_vehicle_change_recomputes_targets(client, pm_headers):
    """Adding/removing vehicles updates per_vehicle task targets."""
    project_id = _new_project(client, pm_headers)
    # Add one vehicle and generate
    r = client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "前移式", "model_name": "Reach-2000", "quantity": 4})
    vid = r.json()["id"]
    r = client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-03"]})  # 单车调试 only
    assert r.status_code == 200

    # Change quantity 4 → 10
    r = client.put(f"/api/projects/{project_id}/vehicles/{vid}", headers=pm_headers,
                   json={"quantity": 10})
    assert r.status_code == 200

    # Tree should show 单车机械与导航调试 target = 10
    r = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    tree = r.json()
    found = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == "单车机械与导航调试":
                    found = t
    assert found is not None
    assert found["target_quantity"] == 10


def test_safety_check_item_cannot_be_ignored(client, pm_headers):
    """Safety-critical check items refuse is_applicable=false."""
    project_id = _new_project(client, pm_headers)
    # Ensure generated
    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    r = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    tree = r.json()
    # Find a safety check item: 紧急停止按钮功能 (ci-027)
    target_ci = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                for ci in t["check_items"]:
                    if "紧急停止按钮" in ci["name"]:
                        target_ci = ci
    assert target_ci is not None
    assert target_ci["is_safety_critical"]

    r = client.put(f"/api/projects/{project_id}/check-items/{target_ci['id']}",
                   headers=pm_headers,
                   json={"is_applicable": False, "not_applicable_reason": "测试忽略"})
    assert r.status_code == 400


def test_regular_check_item_can_be_ignored_with_reason(client, pm_headers):
    """Non-safety check item needs a reason to be ignored."""
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    r = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    tree = r.json()
    target_ci = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                for ci in t["check_items"]:
                    if not ci["is_safety_critical"]:
                        target_ci = ci
                        break
                if target_ci: break
            if target_ci: break
        if target_ci: break

    # Without reason → 400
    r = client.put(f"/api/projects/{project_id}/check-items/{target_ci['id']}",
                   headers=pm_headers, json={"is_applicable": False})
    assert r.status_code == 400

    # With reason → OK
    r = client.put(f"/api/projects/{project_id}/check-items/{target_ci['id']}",
                   headers=pm_headers,
                   json={"is_applicable": False, "not_applicable_reason": "本项目无此工序"})
    assert r.status_code == 200
    assert r.json()["is_applicable"] is False

    # Restore → OK
    r = client.put(f"/api/projects/{project_id}/check-items/{target_ci['id']}",
                   headers=pm_headers, json={"is_applicable": True})
    assert r.status_code == 200
    assert r.json()["is_applicable"] is True


def test_generation_is_idempotent(client, pm_headers):
    """Re-generating the same module doesn't duplicate tasks."""
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-05"]})
    r1 = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    count1 = sum(len(m["tasks"]) for ph in r1.json() for m in ph["modules"])

    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-05"]})
    r2 = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    count2 = sum(len(m["tasks"]) for ph in r2.json() for m in ph["modules"])

    assert count1 == count2 == 4  # 系统部署 module has 4 tasks


# ===== 看板：跨阶段/跨模块移动 =====


def _project_with_two_phases(client, pm_headers):
    """Generate tasks for two modules in different phases; return (pid, tree)."""
    pid = _new_project(client, pm_headers, "看板移动测试项目")
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-01", "mod-03"]})
    assert r.status_code == 200, r.json()
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    return pid, r.json()


def test_move_task_across_phases(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    assert len(tree) >= 2
    phase1, phase2 = tree[0], tree[1]

    # Pick the first task of phase 1
    task = phase1["modules"][0]["tasks"][0]
    task_name = task["name"]

    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"phase_id": phase2["id"]}, 'Task'))
    assert r.status_code == 200, r.json()

    # Task now lives under phase 2, gone from phase 1
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    new_tree = r.json()
    found = None
    for ph in new_tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["name"] == task_name:
                    found = (ph, t)
    assert found is not None
    assert found[0]["id"] == phase2["id"]
    # Quantity fields unchanged
    assert found[1]["target_quantity"] == task["target_quantity"]

    # Audit log contains the move
    r = client.get(f"/api/projects/{pid}/logs", headers=pm_headers)
    details = [l["detail"] for l in r.json()]
    assert any("移动任务" in d and "→" in d for d in details)


def test_move_task_to_same_phase_is_noop(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"phase_id": tree[0]["id"]}, 'Task'))
    assert r.status_code == 200
    # Still in phase 1
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree2 = r.json()
    names = {t["name"] for m in tree2[0]["modules"] for t in m["tasks"]}
    assert task["name"] in names


def test_move_task_phase_and_module_conflict_400(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    target_mod = tree[1]["modules"][0]["id"]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"phase_id": tree[1]["id"], "module_id": target_mod}, 'Task'))
    assert r.status_code == 400


def test_move_task_unknown_phase_404(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"phase_id": "phase-does-not-exist"}, 'Task'))
    assert r.status_code == 404


def test_move_task_unknown_module_404(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"module_id": "mod-does-not-exist"}, 'Task'))
    assert r.status_code == 404


def test_move_task_by_module_id(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    target_mod = tree[1]["modules"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"module_id": target_mod["id"]}, 'Task'))
    assert r.status_code == 200

    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree2 = r.json()
    assert any(t["id"] == task["id"] for m in tree2[1]["modules"] for t in m["tasks"])


def test_move_task_worker_forbidden(client, pm_headers, worker_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=worker_headers,
                   json=versioned(task['id'], {"phase_id": tree[1]["id"]}, 'Task'))
    assert r.status_code in (403, 404)
