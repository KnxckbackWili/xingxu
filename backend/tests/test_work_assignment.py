"""One field assignment flows through project, staffing and personal calendars."""

def setup_work(client, headers):
    p = client.post('/api/projects', headers=headers, json={'name':'现场追加安排', 'status':'planning', 'start_date':'2026-09-01','end_date':'2026-12-31'}).json()['id']
    assert client.put(f'/api/projects/{p}', headers=headers, json={'members':['user-worker-001','user-worker-002']}).status_code == 200
    u = client.post(f'/api/projects/{p}/vehicle-units', headers=headers, json={'asset_code':'AGV-900','current_stage':'planned'}).json()['id']
    e = client.post(f'/api/projects/{p}/vehicle-units/{u}/events', headers=headers, json={'event_type':'fault','event_date':'2026-09-16','title':'驱动轮故障','is_closed':False,'status_after':'fault'}).json()['id']
    return p,u,e


def test_repair_shared_id_survives_regeneration_and_reassigns(client, pm_headers, worker_headers):
    p,u,e = setup_work(client, pm_headers)
    url = f'/api/projects/{p}/vehicle-units/{u}/events/{e}/schedule'
    body = {'assignee_id':'user-worker-001','work_date':'2026-09-16','estimated_hours':5,'notes':'携带驱动轮'}
    first = client.post(url, headers=pm_headers, json=body)
    assert first.status_code == 200, first.text
    ids = first.json()
    assert ids['created'] is True
    duplicate = client.post(url, headers=pm_headers, json={**body, 'estimated_hours': 9, 'notes': '重复请求不应覆盖原备注'})
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()['created'] is False
    assert duplicate.json()['entry_id'] == ids['entry_id']
    assert duplicate.json()['task_id'] == ids['task_id']
    entry = next(x for x in client.get(f'/api/projects/{p}/schedule',headers=pm_headers).json() if x['id']==ids['entry_id'])
    assert entry['source_vehicle_event_id']==e and entry['is_confirmed'] and entry['is_locked']
    assert entry['notes'] == body['notes']
    personal = client.get('/api/dashboard/people-plan?from_date=2026-09-14&to_date=2026-09-20', headers=worker_headers).json()['entries']
    assert next(x for x in personal if x['entry_id']==ids['entry_id'])['assignee_id']=='user-worker-001'
    board = client.get('/api/dashboard/staffing?from_date=2026-09-14&to_date=2026-09-20',headers=pm_headers)
    assert board.status_code==200,board.text
    assert next(x for x in board.json()['entries'] if x['entry_id']==ids['entry_id'])['estimated_hours']==5
    assert client.post(f'/api/projects/{p}/schedule/generate',headers=pm_headers).status_code==200
    preserved = next(x for x in client.get(f'/api/projects/{p}/schedule',headers=pm_headers).json() if x['id']==ids['entry_id'])
    update={'assignee_id':'user-worker-002','work_date':'2026-09-17','version':preserved['version']}
    assert client.put(f"/api/schedule/{ids['entry_id']}",headers=pm_headers,json=update).status_code==200
    assert client.put(f"/api/schedule/{ids['entry_id']}",headers=pm_headers,json=update).status_code==409
    updated=client.get('/api/dashboard/people-plan?from_date=2026-09-14&to_date=2026-09-20',headers=pm_headers).json()['entries']
    updated=[x for x in updated if x['entry_id']==ids['entry_id']]
    assert len(updated)==1 and updated[0]['work_date']=='2026-09-17' and updated[0]['assignee_id']=='user-worker-002'


def test_repair_rejects_wrong_person_scope_and_closed_fault(client,pm_headers,worker_headers):
    p,u,e=setup_work(client,pm_headers)
    url=f'/api/projects/{p}/vehicle-units/{u}/events/{e}/schedule'
    body={'assignee_id':'user-worker-001','work_date':'2026-09-16'}
    assert client.post(url,headers=worker_headers,json=body).status_code==403
    assert client.post(url,headers=pm_headers,json={**body,'assignee_id':'missing'}).status_code==400
    assert client.post(f'/api/projects/{p}/vehicle-units/missing/events/{e}/schedule',headers=pm_headers,json=body).status_code==404
    close=client.put(f'/api/projects/{p}/vehicle-units/{u}/events/{e}',headers=pm_headers,json={'is_closed':True,'verification':'试运行正常','status_after':'normal'})
    assert close.status_code==200,close.text
    assert client.post(url,headers=pm_headers,json=body).status_code==400


def test_manual_work_and_bounded_board(client,pm_headers,worker_headers):
    p,_,_=setup_work(client,pm_headers)
    response=client.post(f'/api/projects/{p}/schedule/manual',headers=pm_headers,json={'title':'客户联调','assignee_id':'user-worker-001','work_date':'2026-09-18','estimated_hours':3})
    assert response.status_code==200,response.text
    ids = response.json()
    assert ids['created'] is True
    duplicate = client.post(f'/api/projects/{p}/schedule/manual', headers=pm_headers, json={
        'task_id': ids['task_id'], 'assignee_id': 'user-worker-001', 'work_date': '2026-09-18',
        'planned_quantity': 7, 'notes': '重复请求不应覆盖数量或备注',
    })
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()['created'] is False
    assert duplicate.json()['entry_id'] == ids['entry_id']
    assert duplicate.json()['task_id'] == ids['task_id']
    entries = client.get(f'/api/projects/{p}/schedule', headers=pm_headers).json()
    entry = next(x for x in entries if x['id'] == ids['entry_id'])
    assert sum(x['id'] == ids['entry_id'] for x in entries) == 1
    assert entry['planned_quantity'] == 1 and entry['notes'] == ''
    assert entry['is_confirmed'] and entry['is_locked']
    assert client.get('/api/dashboard/staffing?from_date=2026-09-01&to_date=2026-12-31',headers=pm_headers).status_code==400
    assert client.get('/api/dashboard/staffing?from_date=2026-09-14&to_date=2026-09-20',headers=worker_headers).status_code==403
    assert client.post(f'/api/projects/{p}/schedule/manual',headers=pm_headers,json={'title':'   ','assignee_id':'user-worker-001','work_date':'2026-09-18'}).status_code==400


def test_cannot_issue_invisible_work_for_paused_or_draft_projects(client,pm_headers):
    from app.db import SessionLocal
    from app.models import Project
    p,_,_=setup_work(client,pm_headers)
    for status in ('draft','suspended','completed','archived'):
        with SessionLocal() as db:
            project=db.get(Project,p);project.status=status;db.commit()
        response=client.post(f'/api/projects/{p}/schedule/manual',headers=pm_headers,json={'title':'不可见安排','assignee_id':'user-worker-001','work_date':'2026-09-18'})
        assert response.status_code==400,response.text
