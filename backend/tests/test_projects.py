"""Project & vehicle tests."""
from tests.lifecycle_helpers import versioned


def test_create_project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "项目CRUD测试",
        "abbreviation": "CRUD",
        "client": "客户A",
        "location": "苏州",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "项目CRUD测试"
    assert data["status"] == "draft"
    assert data["id"]


def test_create_project_invalid_dates(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "日期错误项目",
        "start_date": "2026-09-30", "new_vehicles": False,
        "end_date": "2026-09-01",
    })
    assert r.status_code == 400


def test_create_project_supports_explicit_start_status(client, pm_headers):
    body = {
        "name": "准备中项目", "start_date": "2026-08-10", "end_date": "2026-09-30",
        "new_vehicles": False, "status": "preparing",
    }
    r = client.post("/api/projects", headers=pm_headers, json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "preparing"
    body["name"] = "非法起始状态"
    body["status"] = "executing"
    assert client.post("/api/projects", headers=pm_headers, json=body).status_code == 400


def test_project_crud_flow(client, pm_headers):
    # Create
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "项目CRUD测试",
        "abbreviation": "CRUD",
        "client": "客户A",
        "location": "苏州",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    }).json()["id"]

    # Update
    r = client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"client": "客户B", "location": "杭州"}))
    assert r.status_code == 200
    assert r.json()["client"] == "客户B"

    # Get
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    assert r.status_code == 200
    assert r.json()["location"] == "杭州"

    # New projects start as draft; preparation/planning are explicit decisions.
    for status in ("preparing", "planning", "ready"):
        r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": status})
        assert r.status_code == 200
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    for status in ("executing", "commissioning", "pilot"):
        r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": status})
        assert r.status_code == 200

    # Invalid transition: pilot -> planning
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "planning"})
    assert r.status_code == 400


def test_vehicle_flow(client, pm_headers):
    # Own project
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "车辆测试项目",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"}).json()["id"]
    project_id = pid
    # Add vehicles
    r = client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式",
        "model_name": "AGV-500",
        "quantity": 5,
    })
    assert r.status_code == 200
    vid = r.json()["id"]

    r = client.post(f"/api/projects/{project_id}/vehicles", headers=pm_headers, json={
        "vehicle_type": "堆高车",
        "model_name": "Fork-1000",
        "quantity": 3,
    })
    assert r.status_code == 200

    # List
    r = client.get(f"/api/projects/{project_id}/vehicles", headers=pm_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2

    # Update quantity
    r = client.put(f"/api/projects/{project_id}/vehicles/{vid}", headers=pm_headers, json={"quantity": 8})
    assert r.status_code == 200
    assert r.json()["quantity"] == 8

    # Vehicle total in project detail
    r = client.get(f"/api/projects/{project_id}", headers=pm_headers)
    assert r.json()["vehicle_total"] == 11

    # Delete
    r = client.delete(f"/api/projects/{project_id}/vehicles/{vid}", headers=pm_headers)
    assert r.status_code == 200
    r = client.get(f"/api/projects/{project_id}/vehicles", headers=pm_headers)
    assert len(r.json()) == 1


def test_worker_visibility(client, worker_headers, pm_headers):
    """Worker not in project members cannot view it."""
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "可见性测试项目",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"}).json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=worker_headers)
    assert r.status_code == 404


def test_project_detail_returns_schedule_summary(client, pm_headers):
    """HYPE-58：项目详情返回轻量排程摘要（total/confirmed），项目壳头部无需再拉全量排程列表。"""
    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "排程摘要项目",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"}).json()["id"]

    # 未排程时 total=0，字段稳定存在
    detail = client.get(f"/api/projects/{pid}", headers=pm_headers).json()
    assert detail["schedule_summary"] == {"total": 0, "confirmed": 0}

    for status in ("preparing", "planning"):
        assert client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": status}).status_code == 200

    # 生成任务 + 排程 + 下达
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": [f"mod-{i:02d}" for i in range(1, 3)]})
    gen = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert gen.status_code == 200, gen.json()
    entries = gen.json()["entries"]
    client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)

    summary = client.get(f"/api/projects/{pid}", headers=pm_headers).json()["schedule_summary"]
    assert summary["total"] == entries
    assert summary["confirmed"] == entries
    assert summary["confirmed"] > 0


def test_member_removal_requires_handover_of_unfinished_released_work(client, pm_headers, worker_headers):
    from datetime import date
    from app.db import SessionLocal
    from app.models import Phase, Module, Task, ScheduleEntry, DailyProgress
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    pid = client.post('/api/projects', headers=pm_headers, json={
        'name': '换人交接', 'start_date': '2026-09-01', 'end_date': '2026-10-31', 'members': [uid],
    }).json()['id']
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [uid]})).status_code == 200
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='实施'); db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='实施'); db.add(module); db.flush()
        task = Task(project_id=pid, module_id=module.id, name='现场调试', target_quantity=2); db.add(task); db.flush()
        entry = ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2026, 9, 30), assignee_id=uid, planned_quantity=2, is_confirmed=True)
        db.add(entry); db.flush()
        eid, tid = entry.id, task.id
        report = DailyProgress(project_id=pid, task_id=tid, schedule_entry_id=eid, work_date=date(2026, 9, 30), user_id=uid, completed_quantity=1, client_uuid='partial')
        db.add(report); db.commit()
    blocked = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [],'member_removal_confirmations':[uid]}))
    assert blocked.status_code == 400
    assert '现场调试' in blocked.text and '2026-09-30' in blocked.text
    assert uid in client.get(f'/api/projects/{pid}', headers=pm_headers).json()['members']
    with SessionLocal() as db:
        assert db.get(ScheduleEntry, eid).assignee_id == uid
        assert db.query(DailyProgress).filter_by(schedule_entry_id=eid).one().completed_quantity == 1
        db.query(DailyProgress).filter_by(schedule_entry_id=eid).one().completed_quantity = 2
        db.commit()
    # 数量已完成但安全检查尚未完成，仍需有人承接。
    from app.models import CheckItem
    with SessionLocal() as db:
        check = CheckItem(task_id=tid, name='安全确认', is_required=True, is_safety_critical=True, is_done=False)
        db.add(check); db.commit()
    blocked = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [],'member_removal_confirmations':[uid]}))
    assert blocked.status_code == 400 and '安全检查' in blocked.text
    with SessionLocal() as db:
        db.query(CheckItem).filter_by(task_id=tid).one().is_done = True
        db.commit()
    # 数量及质量已完成，即使 status 仍 planned 也能移出；历史关联完整保留。
    removed = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [],'member_removal_confirmations':[uid]}))
    assert removed.status_code == 200, removed.text
    with SessionLocal() as db:
        assert db.get(ScheduleEntry, eid).assignee_id == uid
        assert db.query(DailyProgress).filter_by(schedule_entry_id=eid).one().completed_quantity == 2


def test_ship_plan_edit_keeps_explicit_preparation_dates(client, pm_headers):
    pid = client.post('/api/projects', headers=pm_headers, json={
        'name': '延期', 'start_date': '2026-09-01', 'end_date': '2026-10-31', 'event_plans': {'ship': '2026-09-15'},
    }).json()['id']
    created = client.post(f'/api/projects/{pid}/procurements', headers=pm_headers, json={'name': '明确采购日期', 'required_date': '2026-09-12'})
    assert created.status_code == 200, created.text
    before = client.get(f'/api/projects/{pid}/procurements', headers=pm_headers).json()['items']
    assert len(before) == 1 and before[0]['required_date'] == '2026-09-12'
    result = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'event_plans': {'ship': '2026-09-25'}}))
    assert next(e for e in result.json()['events'] if e['event_key'] == 'ship')['planned_date'] == '2026-09-25'
    after = client.get(f'/api/projects/{pid}/procurements', headers=pm_headers).json()['items']
    assert [(i['id'], i['required_date']) for i in before] == [(i['id'], i['required_date']) for i in after]
    result = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'event_plans': {'ship': None}}))
    assert next(e for e in result.json()['events'] if e['event_key'] == 'ship')['planned_date'] is None


def test_quality_handover_requires_confirmed_current_successor(client, pm_headers, worker_headers):
    from datetime import date
    from app.db import SessionLocal
    from app.models import Phase, Module, Task, ScheduleEntry, CheckItem, User
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    pid = client.post('/api/projects', headers=pm_headers, json={
        'name': '质量交接', 'start_date': '2026-09-01', 'end_date': '2026-10-31',
    }).json()['id']
    with SessionLocal() as db:
        successor_id = db.query(User).filter_by(username='worker2').one().id
    client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [uid, successor_id]}))
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='实施'); db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='实施'); db.add(module); db.flush()
        task = Task(project_id=pid, module_id=module.id, name='已确认数量但待安全验收', target_quantity=1, manually_completed=True)
        db.add(task); db.flush()
        db.add(CheckItem(task_id=task.id, name='安全验收', is_safety_critical=True, is_done=False))
        old = ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2026,9,30), assignee_id=uid, planned_quantity=1, is_confirmed=True, status='done')
        next_entry = ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2026,10,1), assignee_id=successor_id, planned_quantity=1, is_confirmed=False)
        db.add_all([old, next_entry]); db.flush(); next_id = next_entry.id; db.commit()
    # 仅是成员或者只有草稿安排，尚未接下质量工作。
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [successor_id],'member_removal_confirmations':[uid]})).status_code == 400
    with SessionLocal() as db:
        db.get(ScheduleEntry, next_id).is_confirmed = True; db.commit()
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [successor_id],'member_removal_confirmations':[uid]})).status_code == 200
