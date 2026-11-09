"""Template + task generation tests."""
from tests.lifecycle_helpers import versioned
from tests.template_work import default_work


def _new_project(client, pm_headers, name="任务生成测试项目"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name,
        "client": "测试客户",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200
    return r.json()["id"]


def test_template_rows_have_seed_content(client, pm_headers):
    tree = client.get("/api/templates/default/items", headers=pm_headers)
    assert tree.status_code == 200, tree.text
    rows = {item["name"]: item for section in tree.json()["sections"] for item in section["items"]}
    assert 15 <= len(rows) <= 30
    single = rows["单车调试"]
    assert single["kind"] == "work" and single["per_vehicle"] and len(single["checks"]) >= 3
    assert rows["场地勘测"]["reference_docs"][0]["filename"] == "现场勘测检查要点.txt"
    assert sum(len(item["files"]) for item in rows.values()) == 53
    requirements = client.get('/api/templates/default/document-requirements', headers=pm_headers).json()
    assert len([row for row in requirements if not row['is_group']]) == 53


def test_template_has_optional_modules(client, pm_headers):
    rows = {item["name"]: item for section in client.get("/api/templates/default/items", headers=pm_headers).json()["sections"] for item in section["items"]}
    for name in ["WMS/MES 对接", "电梯/自动门对接", "PLC 对接"]:
        assert rows[name]["optional"], f"缺少可选事项: {name}"


def _tree_tasks(tree):
    return {t["name"]: t for ph in tree for t in ph["work_items"]}


def test_generate_tasks_with_vehicles(client, pm_headers):
    """v3：逐车工作关联真实车辆环节，不再生成目标数量。"""
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 5})
    client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "堆高车", "model_name": "Fork-1000", "quantity": 3})
    r = client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                    json={"work_item_ids": default_work(*[f"mod-{i:02d}" for i in range(1, 9)])})
    assert r.status_code == 200, r.json()
    assert r.json()["tasks"] >= 8
    tree = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers).json()
    tasks = _tree_tasks(tree)
    opening = tasks["到场点检"]
    assert opening["kind"] == "vehicle"
    assert opening["vehicle_step_key"] == "arrival_inspection"
    assert tasks["单车调试"]["vehicle_step_key"] == "single_commissioning"
    server_task = tasks["服务器与网络部署"]
    assert server_task["kind"] != "vehicle"
    progress = client.get(f"/api/projects/{project_id}/vehicle-progress", headers=pm_headers)
    assert progress.status_code == 200, progress.text


def test_per_vehicle_safety_checks_are_frozen_vehicle_definitions(client, pm_headers):
    """逐车工作的安全检查冻结为逐车检查定义（不在工作级别勾选或忽略）。"""
    from app.db import SessionLocal
    from app.models import VehicleCheckDefinition
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-03")})
    task = _tree_tasks(client.get(f"/api/projects/{project_id}/tree", headers=pm_headers).json())["单车调试"]
    assert task["kind"] == "vehicle" and task["check_items"] == []
    with SessionLocal() as db:
        definitions = {d.name: d for d in db.query(VehicleCheckDefinition).filter_by(task_id=task["id"])}
    assert definitions["急停、触边与失速保护"].is_safety_critical


def test_regular_check_item_can_be_ignored_with_reason(client, pm_headers):
    """Non-safety check item needs a reason to be ignored."""
    project_id = _new_project(client, pm_headers)
    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-01")})
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
                json={"work_item_ids": default_work("mod-05")})
    r1 = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    count1 = sum(len(ph["work_items"]) for ph in r1.json())

    client.post(f"/api/projects/{project_id}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-05")})
    r2 = client.get(f"/api/projects/{project_id}/tree", headers=pm_headers)
    count2 = sum(len(ph["work_items"]) for ph in r2.json())

    assert count1 == count2 == 1  # 服务器与网络部署 is one row


# ===== 看板：跨阶段/跨模块移动 =====


def _project_with_two_phases(client, pm_headers):
    """Generate tasks for two modules in different phases; return (pid, tree)."""
    pid = _new_project(client, pm_headers, "看板移动测试项目")
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"work_item_ids": default_work("mod-01", "mod-03")})
    assert r.status_code == 200, r.json()
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    return pid, r.json()


def test_move_task_across_phases(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    assert len(tree) >= 2
    phase1, phase2 = tree[0], tree[1]

    # Pick the first task of phase 1
    task = phase1["work_items"][0]
    task_name = task["name"]

    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"phase_id": phase2["id"]}, 'Task'))
    assert r.status_code == 200, r.json()

    # Task now lives under phase 2, gone from phase 1
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    new_tree = r.json()
    found = None
    for ph in new_tree:
        for t in ph["work_items"]:
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
    task = tree[0]["work_items"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"phase_id": tree[0]["id"]}, 'Task'))
    assert r.status_code == 200
    # Still in phase 1
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree2 = r.json()
    names = {t["name"] for t in tree2[0]["work_items"]}
    assert task["name"] in names


def test_move_task_unknown_phase_404(client, pm_headers):
    pid, tree = _project_with_two_phases(client, pm_headers)
    task = tree[0]["work_items"][0]
    r = client.put(f"/api/projects/{pid}/tasks/{task['id']}", headers=pm_headers,
                   json=versioned(task['id'], {"phase_id": "phase-does-not-exist"}, 'Task'))
    assert r.status_code == 404

