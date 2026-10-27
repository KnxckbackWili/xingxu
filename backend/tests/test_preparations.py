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


def test_status_warnings_on_executing(client, pm_headers):
    pid = _project(client, pm_headers, status="ready")
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()['status'] == 'ready'
    # 未满足条件必须先明确批准风险；批准后仍保留警告
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200
    assert len(r.json().get("warnings", [])) >= 1
    assert "风险进场" in r.json()["warnings"][0]


def test_status_warning_preview_does_not_change_status(client, pm_headers):
    pid = _project(client, pm_headers, status="ready")
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()['status'] == 'ready'
    r = client.post(
        f"/api/projects/{pid}/status",
        headers=pm_headers,
        json={"status": "executing", "confirm_warnings": False},
    )
    assert r.status_code == 400
    assert "风险" in r.json()["detail"]["message"]
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "ready"

    r = client.post(
        f"/api/projects/{pid}/status",
        headers=pm_headers,
        json={"status": "executing", "confirm_warnings": True},
    )
    assert r.status_code == 400
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200
    assert r.json()["requires_confirmation"] is False
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["status"] == "executing"


def test_confirm_ready(client, pm_headers):
    pid = _project(client, pm_headers)
    assert client.post(f'/api/projects/{pid}/preparations/confirm-ready',headers=pm_headers,json={'risk_entry':True,'conclusion':'旧接口'}).status_code == 410
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client,pm_headers,pid)
    result=client.get(f'/api/projects/{pid}',headers=pm_headers).json()
    assert result['prep_confirmed_by'] is not None
    assert '具体说明' in result['prep_conclusion']


def test_worker_read_only(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    # worker 非成员不可见
    r = client.get(f"/api/projects/{pid}/procurements", headers=worker_headers)
    assert r.status_code == 404
    # 加为成员后可读
    client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": ["user-worker-001"]}))
    r = client.get(f"/api/projects/{pid}/procurements", headers=worker_headers)
    assert r.status_code == 200
    # 写被拒（无 manage_plan 能力）
    r = client.post(f"/api/projects/{pid}/procurements", headers=worker_headers,
                    json={"category": "scope", "name": "x"})
    assert r.status_code == 403


# ===== 模板采购清单（v1.3 采购项模板化） =====

def _proc_items(client, headers, tid="default"):
    r = client.get(f"/api/templates/{tid}/procurements", headers=headers)
    assert r.status_code == 200
    return r.json()


def test_template_procurements_crud_and_audit(client, pm_headers, worker_headers, admin_headers):
    """模板采购项 CRUD + 审计；worker 无写权限。"""
    items = _proc_items(client, pm_headers)
    assert len(items) >= 6  # 默认模板种子采购项
    names = {i["name"] for i in items}
    assert {"车载工控机", "安全围栏", "AGV 本体"} <= names
    agg = next(i for i in items if i["name"] == "AGV 本体")
    assert agg["unit"] == "台"
    assert agg["risk"] == "high"

    # 添加（审计）
    r = client.post("/api/templates/default/procurements", headers=admin_headers, json={
        "name": "反光贴纸", "unit": "卷", "spec": "黄黑警示",
        "is_required": False, "risk": "low",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    # 编辑
    r = client.put(f"/api/templates/default/procurements/{pid}", headers=admin_headers,
                   json={"name": "反光贴纸", "unit": "卷", "spec": "黄黑警示",
                         "is_required": False, "risk": "low"})
    assert r.status_code == 200
    assert client.get("/api/templates/default/procurements", headers=pm_headers).json()[0]["name"] != "反光贴纸"  # 排序首个不是它

    # worker 无写权限
    r = client.post("/api/templates/default/procurements", headers=worker_headers,
                    json={"name": "x"})
    assert r.status_code == 403

    # 删除
    r = client.delete(f"/api/templates/default/procurements/{pid}", headers=admin_headers)
    assert r.status_code == 200
    assert all(i["id"] != pid for i in _proc_items(client, pm_headers))


def test_template_clone_copies_procurements(client, pm_headers, admin_headers):
    """复制模板 → 采购项一并复制。"""
    r = client.post("/api/templates", headers=admin_headers,
                    json={"name": "采购复制测试", "copy_from": "default"})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    items = _proc_items(client, pm_headers, tid)
    assert len(items) == len(_proc_items(client, pm_headers, "default"))
    names = {i["name"] for i in items}
    assert "车载工控机" in names
    # 用户模板改采购项不影响默认模板
    agg = next(i for i in items if i["name"] == "车载工控机")
    r = client.put(f"/api/templates/{tid}/procurements/{agg['id']}", headers=admin_headers,
                   json={"name": "车载工控机（高配）", "unit": "台",
                         "spec": "", "is_required": True,
                         "risk": "low"})
    assert r.status_code == 200
    assert any(i["name"] == "车载工控机（高配）" for i in _proc_items(client, pm_headers, tid))
    assert not any(i["name"] == "车载工控机（高配）" for i in _proc_items(client, pm_headers, "default"))
    # 清理
    r = client.delete(f"/api/templates/{tid}", headers=admin_headers)
    assert r.status_code == 200


def test_template_list_exposes_single_system_default(client, pm_headers):
    """The virtual default and its legacy metadata row must not appear twice."""
    r = client.get("/api/templates", headers=pm_headers)
    assert r.status_code == 200
    defaults = [item for item in r.json() if item["name"] == "系统默认模板"]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "default"
    assert defaults[0]["is_system"] is True


# ===== 评审确认 → 已就绪（HYPE-36：_summary 状态机补齐 ready 分支） =====

def test_review_confirm_summary_becomes_ready(client, pm_headers):
    from tests.test_dispatch_review_t29 import scope, confirm
    from tests.test_project_documents import upload
    pid, doc=scope(client,pm_headers)
    assert client.post(f'/api/projects/{pid}/procurements',headers=pm_headers,json={'name':'采购项'}).status_code == 200
    base=f'/api/projects/{pid}/procurements'
    for row in client.get(base,headers=pm_headers).json()['items']:
        assert client.put(base+'/'+row['id'],headers=pm_headers,json={'status':'passed'}).status_code == 200
    summary=client.get(base,headers=pm_headers).json()['summary']
    assert summary['done'] == summary['total']
    assert not summary['dispatch_readiness']['entry_confirmed']
    assert upload(client,pm_headers,pid,[doc['id']]).status_code == 200
    result=confirm(client,pm_headers,pid,conclusion='ready')
    assert result.status_code == 200
    assert result.json()['summary']['state_key']=='ready' and not result.json()['summary']['void']


def test_material_change_reopens_preparation_and_preserves_review(client, pm_headers):
    from tests.test_dispatch_review_t29 import preview, confirm
    pid=_project(client,pm_headers);base=f'/api/projects/{pid}/procurements'
    item=client.post(base,headers=pm_headers,json={'name':'追加采购','status':'passed','actual_date':'2026-09-10','extra':{'quantity':10,'unit':'件','spec':'A'}}).json()
    assert confirm(client,pm_headers,pid).status_code == 200
    token=preview(client,pm_headers,pid)['review_token']
    changed=client.put(base+'/'+item['id'],headers=pm_headers,json={'extra':{'quantity':20},'status':'passed'})
    assert changed.status_code==200 and changed.json()['status']=='pending' and changed.json()['actual_date'] is None
    assert changed.json()['extra']=={'quantity':20,'unit':'件','spec':'A'}
    assert client.get(base,headers=pm_headers).json()['summary']['dispatch_readiness']['entry_confirmed']
    assert confirm(client,pm_headers,pid,token=token).status_code==200
    from app.db import SessionLocal
    from app.models import ProjectReadinessReview
    with SessionLocal() as db:
        assert all(row.get('id')!=item['id'] for review in db.query(ProjectReadinessReview).filter_by(project_id=pid) for row in review.snapshot)
    logs=client.get(f'/api/projects/{pid}/logs',headers=pm_headers).json()
    assert any('需求数量/规格/单位变化' in row['detail'] for row in logs)


def test_spec_change_rechecks_procurement_without_changing_document_risk_approval(client, pm_headers):
    from tests.test_dispatch_review_t29 import confirm
    pid=_project(client,pm_headers);base=f'/api/projects/{pid}/procurements'
    item=client.post(base,headers=pm_headers,json={'name':'电源','extra':{'quantity':1,'spec':'220V'}}).json()
    assert confirm(client,pm_headers,pid).status_code==200
    changed=client.put(base+'/'+item['id'],headers=pm_headers,json={'extra':{'spec':'380V'}})
    assert changed.status_code==200 and changed.json()['extra']['spec']=='380V'
    assert client.get(base,headers=pm_headers).json()['summary']['dispatch_readiness']['entry_confirmed']


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


def test_legacy_future_procurement_completion_stays_visible_without_becoming_document_evidence(client, pm_headers):
    from datetime import date,timedelta
    from app.db import SessionLocal
    from app.models import ProjectPreparationItem
    from tests.test_dispatch_review_t29 import preview, confirm
    pid=_project(client,pm_headers);base=f'/api/projects/{pid}/procurements'
    original=client.get(base,headers=pm_headers).json();today=date.fromisoformat(original['summary']['today']);item=original['items'][0]
    with SessionLocal() as db:
        for row in db.query(ProjectPreparationItem).filter_by(project_id=pid):row.status='passed';row.actual_date=today
        db.get(ProjectPreparationItem,item['id']).actual_date=today+timedelta(days=1);db.commit()
    after=client.get(base,headers=pm_headers).json()
    assert after['summary']['done']==after['summary']['total']-1
    assert all(row.get('id')!=item['id'] for row in preview(client,pm_headers,pid)['entry_unmet'])
    assert confirm(client,pm_headers,pid,conclusion='ready').status_code==400
    assert next(row for row in after['items'] if row['id']==item['id'])['actual_date']==(today+timedelta(days=1)).isoformat()
