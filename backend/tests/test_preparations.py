import pytest
"""Project preparation (准备 Tab) tests."""
from tests.lifecycle_helpers import versioned


def _project(client, pm_headers, name="准备项目", status=None, with_procurement=True):
    body = {
        "name": name, "start_date": "2026-09-01", "end_date": "2026-10-31",
        "event_plans": {"ship": "2026-09-15"},
    }
    r = client.post("/api/projects", headers=pm_headers, json=body)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    if status is not None:
        from app.db import SessionLocal
        from app.models import Project
        with SessionLocal() as db:
            db.get(Project,pid).status=status;db.commit()
        if status == 'preparing':
            from tests.lifecycle_helpers import submit_kickoff_documents
            submit_kickoff_documents(client, pm_headers, pid)
    if with_procurement:
        created = client.post(f'/api/projects/{pid}/procurements', headers=pm_headers,
            json={'name': '采购前置条件', 'category': 'procurement', 'is_required': True, 'blocks_entry': True})
        assert created.status_code == 200, created.text
    return pid


def test_new_project_keeps_procurement_explicit_and_materials_in_documents(client, pm_headers):
    from tests.document_helpers import documents
    pid = _project(client, pm_headers, with_procurement=False)
    data = client.get(f'/api/projects/{pid}/procurements', headers=pm_headers).json()
    assert data['items'] == [] and data['summary']['total'] == 0
    assert data['summary']['planned_ship_date'] == '2026-09-15'
    state = documents(client, pm_headers, pid)
    assert len([row for row in state['definitions'] if row['stage_key'] != 'legacy']) == 53
    assert all(row['stage_key'] != 'legacy' for row in state['documents'])
    assert all(row['status'] == 'pending' for row in state['documents'])
    assert client.post(f'/api/projects/{pid}/preparations/seed', headers=pm_headers).status_code == 404


def test_procurements_are_explicitly_selected_from_catalog(client, pm_headers):
    pid = _project(client, pm_headers, "按需采购项目")
    catalog = client.get("/api/templates/default/procurements", headers=pm_headers).json()
    selected = [next(item for item in catalog if item["name"] == "AGV 本体")]

    r = client.post(
        f"/api/projects/{pid}/procurements/import",
        headers=pm_headers,
        json={"items": [{"item_id": selected[0]["id"], "quantity": 5}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1

    items = client.get(f"/api/projects/{pid}/procurements", headers=pm_headers).json()["items"]
    agv = next(item for item in items if item["name"] == "AGV 本体")
    assert agv["category"] == "procurement"
    assert agv["extra"]["source"] == "catalog"
    assert agv["required_date"] == "2026-09-15"

    duplicate = client.post(
        f"/api/projects/{pid}/procurements/import",
        headers=pm_headers,
        json={"items": [{"item_id": selected[0]["id"], "quantity": 5}]},
    )
    assert duplicate.json() == {"created": 0, "skipped": 1}


def test_crud_and_audit(client, pm_headers):
    pid = _project(client, pm_headers)
    # create
    r = client.post(f"/api/projects/{pid}/procurements", headers=pm_headers, json={
        "category": "procurement", "name": "自动充电桩", "blocks_entry": True,
        "owner_party": "procurement", "risk": "high", "planned_date": "2026-09-01",
        "extra": {"quantity": 2, "unit": "套", "order_status": "已下单"},
    })
    assert r.status_code == 200, r.text
    iid = r.json()["id"]
    assert r.json()["extra"]["quantity"] == 2
    # update 状态 → 记录实际日期
    r = client.put(f"/api/projects/{pid}/procurements/{iid}", headers=pm_headers, json={"status": "passed"})
    assert r.status_code == 200
    assert r.json()["actual_date"] is not None
    # delete
    r = client.delete(f"/api/projects/{pid}/procurements/{iid}", headers=pm_headers)
    assert r.status_code == 200
    # 变更记录
    r = client.get(f"/api/projects/{pid}/logs", headers=pm_headers)
    bodies = [x.get("detail", "") for x in r.json()]
    assert any("准备项「自动充电桩」" in b for b in bodies)


# ===== 模板采购清单（v1.3 采购项模板化） =====


def test_template_list_exposes_single_system_default(client, pm_headers):
    """The virtual default and its legacy metadata row must not appear twice."""
    r = client.get("/api/templates", headers=pm_headers)
    assert r.status_code == 200
    defaults = [item for item in r.json() if item["name"] == "通用模板"]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "default"
    assert defaults[0]["is_system"] is True


# ===== 评审确认 → 已就绪（HYPE-36：_summary 状态机补齐 ready 分支） =====

def test_preparation_owner_can_be_set_cleared_and_validated(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    base = f"/api/projects/{pid}/procurements"
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    item = client.post(base, headers=pm_headers, json={"name": "协调", "owner_id": uid}).json()
    assert item['owner_id'] == uid
    result = client.put(f"{base}/{item['id']}", headers=pm_headers, json={"owner_id": None})
    assert result.status_code == 200
    assert result.json()['owner_id'] is None
    assert client.put(f"{base}/{item['id']}", headers=pm_headers, json={"owner_id": 'missing'}).status_code == 400


def test_actual_completion_rejects_future_date_without_changing_item_or_count(client, pm_headers):
    from datetime import timedelta
    pid = _project(client, pm_headers)
    base = f"/api/projects/{pid}/procurements"
    original = client.get(base, headers=pm_headers).json()
    from datetime import date
    future = (date.fromisoformat(original['summary']['today']) + timedelta(days=1)).isoformat()
    rejected = client.post(base, headers=pm_headers, json={
        'name': '未来不是实际完成', 'status': 'passed', 'actual_date': future,
    })
    assert rejected.status_code == 400 and '当前预计' in rejected.json()['detail']
    item = original['items'][0]
    rejected = client.put(f"{base}/{item['id']}", headers=pm_headers, json={
        'status': 'passed', 'actual_date': future,
    })
    assert rejected.status_code == 400
    after = client.get(base, headers=pm_headers).json()
    assert after['summary']['done'] == original['summary']['done']
    assert next(row for row in after['items'] if row['id'] == item['id']) == item
    # Future estimates remain supported, and a real completion can use the site date.
    saved = client.put(f"{base}/{item['id']}", headers=pm_headers, json={
        'status': 'passed', 'actual_date': original['summary']['today'], 'forecast_date': future,
    })
    assert saved.status_code == 200 and saved.json()['forecast_date'] == future


def test_completion_uses_project_calendar_instead_of_host_date(client, pm_headers, monkeypatch):
    from datetime import date
    pid = _project(client, pm_headers)
    project = client.get(f'/api/projects/{pid}', headers=pm_headers).json()
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json={
        'timezone': 'America/New_York', 'version': project['version'],
    }).status_code == 200
    seen = []
    def local_day(zone):
        seen.append(zone)
        return date(2026, 10, 4)
    monkeypatch.setattr('app.time_utils.project_today', local_day)
    base = f"/api/projects/{pid}/procurements"
    rejected = client.post(base, headers=pm_headers, json={
        'name': '现场仍是昨日', 'status': 'passed', 'actual_date': '2026-10-05',
    })
    assert rejected.status_code == 400 and '2026-10-04' in rejected.json()['detail']
    saved = client.post(base, headers=pm_headers, json={'name': '现场今日完成', 'status': 'passed'})
    assert saved.status_code == 200 and saved.json()['actual_date'] == '2026-10-04'
    # The direct list action sends no host date, including on an existing item.
    pending = client.post(base, headers=pm_headers, json={'name': '就地确认现场日期', 'status': 'pending'}).json()
    updated = client.put(f"{base}/{pending['id']}", headers=pm_headers, json={'status': 'passed', 'actual_date': None})
    assert updated.status_code == 200 and updated.json()['actual_date'] == '2026-10-04'
    assert seen and set(seen) == {'America/New_York'}


def test_inline_fields_keep_other_data_and_arrival_does_not_claim_readiness(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    base = f"/api/projects/{pid}/procurements"
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    item = client.post(base, headers=pm_headers, json={
        'name': '快捷采购跟进', 'category': 'procurement', 'status': 'pending',
        'owner_party': 'procurement', 'note': '保留验收要求', 'forecast_date': '2026-10-20',
        'extra': {'quantity': 2, 'unit': '套', 'spec': 'A型', 'order_status': '采购中'},
    }).json()
    updated = client.put(f"{base}/{item['id']}", headers=pm_headers, json={'owner_id': uid, 'owner_party': 'production'})
    assert updated.status_code == 200
    assert updated.json()['owner_id'] == uid and updated.json()['owner_party'] == 'production'
    assert updated.json()['note'] == '保留验收要求' and updated.json()['forecast_date'] == '2026-10-20'
    arrived = client.put(f"{base}/{item['id']}", headers=pm_headers, json={'extra': {'order_status': '已到货'}})
    assert arrived.status_code == 200
    assert arrived.json()['extra'] == {'quantity': 2, 'unit': '套', 'spec': 'A型', 'order_status': '已到货'}
    assert arrived.json()['status'] == 'pending' and arrived.json()['actual_date'] is None
    today = client.get(base, headers=pm_headers).json()['summary']['today']
    completed = client.put(f"{base}/{item['id']}", headers=pm_headers, json={'status': 'passed', 'actual_date': None}).json()
    assert completed['actual_date'] == today and completed['completed_by']
    reopened = client.put(f"{base}/{item['id']}", headers=pm_headers, json={'status': 'pending', 'actual_date': None}).json()
    assert reopened['actual_date'] is None and reopened['completed_by'] is None and reopened['completed_at'] is None
    cleared = client.put(f"{base}/{item['id']}", headers=pm_headers, json={'owner_id': None}).json()
    assert cleared['owner_id'] is None and cleared['note'] == '保留验收要求'
    assert cleared['extra']['order_status'] == '已到货' and cleared['extra']['spec'] == 'A型'

