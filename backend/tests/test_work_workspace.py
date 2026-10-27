"""Shared work detail is one permission-scoped view of existing records."""
from tests.test_work_assignment import setup_work, repair


def assigned_repair(client, headers):
    """Fault repair placed into this week's plan (v3: weekly plans replace daily repair scheduling)."""
    p, unit, event = setup_work(client, headers)
    result = repair(client, headers, p, unit, event, ['user-worker-001'])
    assert result.status_code == 200, result.text
    return p, unit, event, result.json()


def test_detail_and_repair_update_original_records(client, pm_headers, worker_headers):
    p, unit, event, ids = assigned_repair(client, pm_headers)
    path = f'/api/projects/{p}/tasks/{ids["task_id"]}/workspace'
    worker = client.get(path, headers=worker_headers).json()
    assert worker['can_report'] and not worker['can_schedule'] and not worker['can_update_repair']
    assert worker['repair']['id'] == event
    assert worker['entries'] == [] and worker['reports'] == []
    # 按日报量已退役：旧入口不再写入新事实。
    retired = client.post('/api/worker/reports', headers=worker_headers, json={
        'task_id': ids['task_id'], 'work_date': '2026-09-17', 'completed_quantity': 1, 'client_uuid': 'workspace-retry-001'})
    assert retired.status_code == 410
    detail = client.get(path, headers=pm_headers).json()
    assert detail['can_schedule'] and detail['can_update_repair'] and detail['reports'] == []
    assert client.put(f'/api/projects/{p}/vehicle-units/{unit}/events/{event}', headers=pm_headers,
        json={'action_taken':'更换驱动轮','verification':'带载运行正常','is_closed':True,'status_after':'normal'}).status_code == 200
    detail = client.get(path,headers=worker_headers).json()
    assert detail['repair']['is_closed'] and detail['repair']['current_status'] == 'normal'
    summary = client.get(f'/api/projects/{p}/handover-summary',headers=pm_headers).json()
    assert summary['counts']['faults'] == 0


def test_detail_and_handover_cannot_leak_another_project(client, pm_headers, worker_headers):
    p, _, _, ids = assigned_repair(client, pm_headers)
    other = client.post('/api/projects',headers=pm_headers,json={'name':'不可见项目','start_date':'2026-09-01','end_date':'2026-12-31'}).json()['id']
    assert client.get(f'/api/projects/{other}/handover-summary',headers=worker_headers).status_code in (403,404)
    assert client.get(f'/api/projects/{other}/tasks/{ids["task_id"]}/workspace',headers=worker_headers).status_code in (403,404)
    assert client.get(f'/api/projects/{other}/tasks/{ids["task_id"]}/workspace',headers=pm_headers).status_code == 404
    assert client.get(f'/api/projects/{p}/tasks/missing/workspace',headers=pm_headers).status_code == 404
    from app.db import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        db.get(Project,p).status='suspended'; db.commit()
    detail=client.get(f'/api/projects/{p}/tasks/{ids["task_id"]}/workspace',headers=pm_headers).json()
    assert not any(detail[k] for k in ('can_schedule','can_report','can_check','can_update_repair'))


def test_handover_counts_material_instances_without_copying_tasks(client, pm_headers):
    from tests.document_helpers import documents, upload_documents, requirement
    from app.db import SessionLocal
    from app.models import Task, Issue
    p, _, _, ids = assigned_repair(client, pm_headers)
    with SessionLocal() as db:
        db.get(Task, ids['task_id']).manually_completed = True
        db.add(Issue(project_id=p, title='客户网络未就绪', status='open', reporter_id='user-pm-001'))
        db.commit()
    doc = requirement(client, pm_headers, p, name='验收记录', code='6.99', required=True)
    optional = requirement(client, pm_headers, p, name='选填资料', code='6.98', required=False)
    rows = documents(client, pm_headers, p)['documents']
    upload_documents(client, pm_headers, p, [row['id'] for row in rows if row['applicable'] and row['id'] not in (doc['id'], optional['id'])])
    result = client.get(f'/api/projects/{p}/handover-summary', headers=pm_headers)
    assert result.status_code == 200, result.text
    summary = result.json()
    assert summary['counts'] == {'tasks': 0, 'issues': 1, 'faults': 1, 'documents': 2}
    assert {row['id'] for row in summary['documents']} == {doc['id'], optional['id']}
    assert summary['documents'][0]['id'] != ids['task_id']
    assert 'deliverables' not in summary
    with SessionLocal() as db:
        assert db.query(Task).filter_by(project_id=p).count() == 1
