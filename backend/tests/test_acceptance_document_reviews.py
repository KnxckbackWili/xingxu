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
    return client.get('/api/auth/me', headers=worker_headers).json()['id']
