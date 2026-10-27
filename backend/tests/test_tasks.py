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


def _tree_tasks(tree):
    return {t["name"]: t for ph in tree for m in ph["modules"] for t in m["tasks"]}


def test_generate_tasks_with_vehicles(client, pm_headers):
    """v3：逐车工作关联真实车辆环节，不再生成目标数量。"""
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 5})
    client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "堆高车", "model_name": "Fork-1000", "quantity": 3})
    core_ids = [f"mod-{i:02d}" for i in range(1, 9)]
    r = client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                    json={"module_ids": core_ids})
    assert r.status_code == 200, r.json()
    assert r.json()["tasks"] > 20
    tree = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers).json()
    assert len(tree) == 8
    tasks = _tree_tasks(tree)
    opening = tasks["开箱检查"]
    assert opening["quantity_type"] == "per_vehicle"
    assert opening["vehicle_step_key"] == "arrival_inspection"
    assert opening["target_quantity"] is None
    assert tasks["单车机械与导航调试"]["vehicle_step_key"] == "single_commissioning"
    server_task = tasks["服务器部署与配置"]
    assert server_task["kind"] != "vehicle" and server_task["target_quantity"] is None
    progress = client.get(f"/api/projects/{project_id}/vehicle-progress", headers=pm_headers)
    assert progress.status_code == 200, progress.text


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
    assert "项目实施范围冻结" not in _tree_tasks(tree)
    # 按天排程已退役：不能借旧入口把准备提醒排进日程。
    assert client.post(f"/api/projects/{project_id}/schedule/generate", headers=pm_headers).status_code == 410
    preparations = client.get(f"/api/projects/{project_id}/procurements", headers=pm_headers)
    assert preparations.status_code == 200
    assert preparations.json()['items'] == []


def test_task_target_quantity_is_read_only(client, pm_headers):
    """车辆数量变化不再回写工作目标；目标数量字段只读。"""
    project_id = _new_project(client, pm_headers)
    vid = client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "前移式", "model_name": "Reach-2000", "quantity": 4}).json()["id"]
    assert client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                       json={"module_ids": ["mod-03"]}).status_code == 200
    assert client.put(f"/api/projects/{project_id}/vehicles/{vid}", headers=pm_headers,
                      json={"quantity": 10}).status_code == 200
    task = _tree_tasks(client.get(f"/api/projects/{project_id}/tree", headers=pm_headers).json())["单车机械与导航调试"]
    assert task["target_quantity"] is None
    r = client.put(f"/api/projects/{project_id}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task["id"], {"target_quantity": 10}, "Task"))
    assert r.status_code == 400 and "只读" in r.json()["detail"]


def test_per_vehicle_safety_checks_are_frozen_vehicle_definitions(client, pm_headers):
    """逐车工作的安全检查冻结为逐车检查定义（不在工作级别勾选或忽略）。"""
    from app.db import SessionLocal
    from app.models import VehicleCheckDefinition
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    task = _tree_tasks(client.get(f"/api/projects/{project_id}/tree", headers=pm_headers).json())["异常急停测试"]
    assert task["quantity_type"] == "per_vehicle" and task["check_items"] == []
    with SessionLocal() as db:
        definitions = {d.name: d for d in db.query(VehicleCheckDefinition).filter_by(task_id=task["id"])}
    assert definitions["紧急停止按钮功能(100ms内断电)"].is_safety_critical


def test_regular_check_item_can_be_ignored_with_reason(client, pm_headers):
    """Non-safety check item needs a reason to be ignored."""
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-01"]})
    from tests.lifecycle_helpers import enter_execution
    enter_execution(client, pm_headers, project_id)  # 检查项只在现场实施期间登记
    tree = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers).json()
    target_ci = next(ci for t in _tree_tasks(tree).values() for ci in t["check_items"] if not ci["is_safety_critical"])
    url = f"/api/projects/{project_id}/check-items/{target_ci['id']}"

    def put(body):
        from app.db import SessionLocal
        from app.models import CheckItem
        with SessionLocal() as db:
            version = db.get(CheckItem, target_ci["id"]).version or 0
        return client.put(url, headers=pm_headers, json={**body, "version": version})

    assert put({"is_applicable": False}).status_code == 400
    r = put({"is_applicable": False, "not_applicable_reason": "本项目无此工序"})
    assert r.status_code == 200, r.text
    assert r.json()["is_applicable"] is False
    r = put({"is_applicable": True})
    assert r.status_code == 200, r.text
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
    # Audit log records the old and new phase of the move
    from app.db import SessionLocal
    from app.models import ChangeLog
    with SessionLocal() as db:
        move = db.query(ChangeLog).filter_by(project_id=pid, entity_id=task["id"], action="update").one()
    assert move.detail == f"修改工作项「{task_name}」"
    assert move.old_value["phase_id"] == phase1["id"] and move.new_value["phase_id"] == phase2["id"]


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


def test_move_task_by_module_id_is_read_only(client, pm_headers):
    """历史模块只作来源，不能再作为工作归属移动；请改用项目阶段。"""
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    for module_id in (tree[1]["modules"][0]["id"], "mod-does-not-exist"):
        r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                       json=versioned(task['id'], {"module_id": module_id}, 'Task'))
        assert r.status_code == 400 and "只读" in r.json()["detail"]
    tree2 = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    assert any(t["id"] == task["id"] for m in tree2[0]["modules"] for t in m["tasks"])


def test_move_task_worker_forbidden(client, pm_headers, worker_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["modules"][0]["tasks"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=worker_headers,
                   json=versioned(task['id'], {"phase_id": tree[1]["id"]}, 'Task'))
    assert r.status_code in (403, 404)
