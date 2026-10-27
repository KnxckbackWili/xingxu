"""验收记录门禁、资料可选审核与通知。"""
from tests.lifecycle_helpers import versioned



def _project(client, pm_headers, name='功能边界项目'):
    r = client.post('/api/projects', headers=pm_headers, json={'name': name, 'start_date': '2026-08-10', 'status': 'preparing', 'new_vehicles': False, 'end_date': '2026-09-30'})
    assert r.status_code == 200, r.json()
    return r.json()['id']

def test_acceptance_record_endpoint(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers, json={'accepted_by_name': '客户', 'accepted_at': '2026-09-30', 'conclusion': 'accepted'})
    assert r.status_code == 400
    from app.db import SessionLocal
    from app.models import Project
    db = SessionLocal()
    try:
        p = db.get(Project, pid)
        p.status = 'acceptance'
        db.commit()
    finally:
        db.close()
    r = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers, json={'accepted_by_name': '客户验收代表', 'accepted_at': '2026-09-30', 'conclusion': 'accepted', 'notes': '现场验收通过'})
    assert r.status_code == 200, r.json()
    records = client.get(f'/api/projects/{pid}/acceptance', headers=pm_headers).json()
    assert len(records) == 1
    assert records[0]['conclusion'] == 'accepted'

def _add_worker(client, pm_headers, worker_headers, pid):
    wid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    r = client.get(f'/api/projects/{pid}', headers=pm_headers)
    members = list(r.json()['members'])
    if wid not in members:
        members.append(wid)
    r = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': members}))
    assert r.status_code == 200, r.json()
    return wid

def test_completed_gate_requires_acceptance_record(client, pm_headers, worker_headers):
    """实车环节与资料齐备仍需真实验收记录，登记工作不自动推进人工阶段。"""
    from app.db import SessionLocal
    from app.models import Project
    from app.time_utils import project_today
    from tests.test_vehicle_progress import setup_fleet, matrix, write
    from tests.document_helpers import complete_documents
    pid, unit_ids = setup_fleet(client, pm_headers, 1)
    _add_worker(client, pm_headers, worker_headers, pid)
    for step in matrix(client, pm_headers, pid)['steps']:
        response = write(client, worker_headers, pid, unit_ids, key=step['key'])
        assert response.status_code == 200, response.text
    complete_documents(client, pm_headers, pid)
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'executing'
    # This test begins at acceptance; separate lifecycle tests cover the signed
    # transition into acceptance. No former quantity or daily-plan write is used.
    with SessionLocal() as db:
        db.get(Project, pid).status = 'acceptance'; db.commit()
    result = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'completed'})
    assert result.status_code == 400, result.text
    assert any(row['type'] == 'acceptance' for row in result.json()['detail']['blockers'])
    assert '验收' in result.json()['detail']['message']
    response = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers, json={
        'accepted_by_name': '客户验收代表', 'accepted_at': project_today('Asia/Shanghai').isoformat(),
        'conclusion': 'accepted', 'notes': '验收通过'})
    assert response.status_code == 200, response.text
    result = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'completed'})
    assert result.status_code == 200, result.text

def test_document_self_review_blocked(client, pm_headers):
    from tests.document_helpers import documents, upload_documents
    pid = _project(client, pm_headers)
    row = documents(client, pm_headers, pid)['documents'][0]
    submitted = upload_documents(client, pm_headers, pid, [row['id']])['documents'][0]
    version = submitted['versions'][0]
    response = client.post(f'/api/projects/{pid}/documents/{row['id']}/versions/{version['id']}/review', headers=pm_headers, json={'decision': 'approved'})
    assert response.status_code == 400 and '不能自己审核' in response.json()['detail']

def test_document_submission_and_review_notify_original_actors(client, pm_headers, worker_headers):
    from tests.document_helpers import documents, upload_documents
    pid = _project(client, pm_headers)
    _add_worker(client, pm_headers, worker_headers, pid)
    row = documents(client, pm_headers, pid)['documents'][0]
    submitted = upload_documents(client, worker_headers, pid, [row['id']])['documents'][0]
    pm_messages = client.get('/api/notifications', headers=pm_headers).json()
    assert any((n['ntype'] == 'document_submitted' and n['entity_id'] == row['id'] for n in pm_messages))
    version = submitted['versions'][0]
    response = client.post(f'/api/projects/{pid}/documents/{row['id']}/versions/{version['id']}/review', headers=pm_headers, json={'decision': 'rejected', 'note': '缺少检测记录'})
    assert response.status_code == 200, response.text
    worker_messages = client.get('/api/notifications', headers=worker_headers).json()
    assert any((n['ntype'] == 'document_reviewed' and n['entity_id'] == row['id'] for n in worker_messages))
