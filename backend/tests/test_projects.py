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
    assert data["status"] == "preparing"
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

    # New projects start in preparing; every later stage is an explicit, gated decision.
    from tests.lifecycle_helpers import enter_execution
    enter_execution(client, pm_headers, pid)
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "executing"

    # Invalid transition: executing -> completed (not adjacent)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "completed"})
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


