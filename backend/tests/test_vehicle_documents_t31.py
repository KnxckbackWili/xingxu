"""T31 one vehicle projection of canonical document instances and versions."""
from tests.lifecycle_helpers import versioned
from app.db import SessionLocal
from app.models import Project, ProjectDocument, DocumentVersion, ChangeLog, User
from tests.test_project_documents import create, view, upload
from tests.test_project_events import unit


def fleet(client,headers):
    pid=create(client,headers,dispatch_platform='NDC',timezone='Asia/Shanghai')['id']
    assert client.put(f'/api/projects/{pid}',headers=headers,json=versioned(pid, {'members':['user-worker-001']})).status_code==200
    with SessionLocal() as db:
        db.get(Project,pid).status='executing';db.commit()
    result=client.post(f'/api/projects/{pid}/vehicles',headers=headers,json={'vehicle_type':'潜伏式','model_name':'T31实车','quantity':2})
    assert result.status_code==200,result.text
    ids=[unit(client,headers,pid,result.json()['id'],f'AGV-{i:03}') for i in (1,2)]
    return pid,ids


def vehicle_view(client,headers,pid,uid):
    result=client.get(f'/api/projects/{pid}/documents',headers=headers,params={'vehicle_unit_id':uid})
    assert result.status_code==200,result.text
    return result.json()


def inspection(rows):
    return next(row for row in rows['documents'] if row['code']=='6.1')


def test_vehicle_projection_is_same_instance_stream_and_get_is_readonly(client,admin_headers):
    pid,ids=fleet(client,admin_headers)
    with SessionLocal() as db:
        before=(db.query(ProjectDocument).filter_by(project_id=pid).count(),db.query(ChangeLog).filter(ChangeLog.project_id==pid,ChangeLog.action!='confidential_view').count())
    filtered=vehicle_view(client,admin_headers,pid,ids[0]);full=view(client,admin_headers,pid)
    expected=[row for row in full['documents'] if row['scope']=='vehicle' and row['vehicle_unit_id']==ids[0]]
    assert filtered['documents']==expected and expected
    assert any(row['code']=='6.11.2a' for row in expected)
    assert any(row['code']=='6.11.2.2' for row in expected)
    assert not any(row['code']=='6.11.2.1' for row in expected)
    assert all(row['scope']=='vehicle' for row in filtered['definitions'])
    assert filtered['unclassified_files']==[]
    for name in ('this_week','overdue','on_demand','owner_warnings'):
        assert all(row['document_id'] in {doc['id'] for doc in expected} for row in filtered['document_actions'][name])
    with SessionLocal() as db:
        assert (db.query(ProjectDocument).filter_by(project_id=pid).count(),db.query(ChangeLog).filter(ChangeLog.project_id==pid,ChangeLog.action!='confidential_view').count())==before


def test_each_real_arrival_sets_only_its_inspection_24_hours_and_clear_keeps_id(client,admin_headers):
    pid,ids=fleet(client,admin_headers)
    first=inspection(vehicle_view(client,admin_headers,pid,ids[0]));second=inspection(vehicle_view(client,admin_headers,pid,ids[1]))
    assert first['due_at'] is None and second['due_at'] is None
    result=client.put(f'/api/projects/{pid}/vehicle-arrivals',headers=admin_headers,json=versioned(pid, {'unit_ids':[ids[0]],'arrived_at':'2026-10-20'}))
    assert result.status_code==200,result.text
    changed=inspection(vehicle_view(client,admin_headers,pid,ids[0]))
    assert changed['id']==first['id'] and changed['due_at']=='2026-10-20T16:00:00+00:00'
    assert changed['due_basis']['actual_date']=='2026-10-20' and changed['due_basis']['precision']=='date'
    assert 'actual_at' not in changed['due_basis']
    assert inspection(vehicle_view(client,admin_headers,pid,ids[1]))['due_at'] is None
    assert client.put(f'/api/projects/{pid}/vehicle-arrivals',headers=admin_headers,json=versioned(pid, {'unit_ids':[ids[1]],'arrived_at':'2026-10-22'})).status_code==200
    assert inspection(vehicle_view(client,admin_headers,pid,ids[1]))['due_at']=='2026-10-22T16:00:00+00:00'
    assert client.put(f'/api/projects/{pid}/vehicle-arrivals',headers=admin_headers,json=versioned(pid, {'unit_ids':[ids[0]],'arrived_at':None,'reason':'原到场日待核对'})).status_code==200
    cleared=inspection(vehicle_view(client,admin_headers,pid,ids[0]))
    assert cleared['id']==first['id'] and cleared['due_at'] is None and cleared['due_state']=='awaiting_event'
    assert inspection(vehicle_view(client,admin_headers,pid,ids[1]))['id']==second['id']


def test_upload_from_car_and_project_views_share_all_versions_and_keep_other_car_pending(client,admin_headers):
    pid,ids=fleet(client,admin_headers)
    doc=inspection(vehicle_view(client,admin_headers,pid,ids[0]))
    response=upload(client,admin_headers,pid,[doc['id']],data=b'car inspection v1')
    assert response.status_code==200,response.text
    current=inspection(vehicle_view(client,admin_headers,pid,ids[0]))
    same=next(row for row in view(client,admin_headers,pid)['documents'] if row['id']==doc['id'])
    assert current==same and current['status']=='submitted'
    assert client.get('/api'+current['latest_version']['download_url'],headers=admin_headers).content==b'car inspection v1'
    assert upload(client,admin_headers,pid,[doc['id']],data=b'car inspection v2').status_code==200
    current=inspection(vehicle_view(client,admin_headers,pid,ids[0]))
    assert len(current['versions'])==2 and current['versions']==next(row for row in view(client,admin_headers,pid)['documents'] if row['id']==doc['id'])['versions']
    assert client.get('/api'+current['versions'][0]['download_url'],headers=admin_headers).content==b'car inspection v1'
    untouched=inspection(vehicle_view(client,admin_headers,pid,ids[1]))
    assert untouched['status']=='pending' and untouched['versions']==[]
    with SessionLocal() as db:
        assert db.query(ProjectDocument).filter_by(project_id=pid,id=doc['id']).count()==1
        assert db.query(DocumentVersion).filter_by(project_document_id=doc['id']).count()==2


def test_filter_rejects_foreign_missing_car_and_hidden_project(client,admin_headers,worker_headers):
    pid,ids=fleet(client,admin_headers);other=create(client,admin_headers)['id']
    assert client.get(f'/api/projects/{other}/documents',headers=admin_headers,params={'vehicle_unit_id':ids[0]}).status_code==404
    assert client.get(f'/api/projects/{pid}/documents',headers=admin_headers,params={'vehicle_unit_id':'missing'}).status_code==404
    assert client.get(f'/api/projects/{other}/documents',headers=worker_headers,params={'vehicle_unit_id':ids[0]}).status_code==404
    assert client.get(f'/api/projects/{pid}/documents',headers=admin_headers,params={'vehicle_unit_id':''}).status_code==422


def test_car_projection_and_download_preserve_confidential_acl_and_submit_revocation(client,admin_headers,worker_headers):
    pid,ids=fleet(client,admin_headers)
    doc=inspection(vehicle_view(client,admin_headers,pid,ids[0]))
    response=upload(client,admin_headers,pid,[doc['id']])
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        db.get(ProjectDocument,doc['id']).confidential=True
        worker=db.query(User).filter_by(username='worker1').one()
        worker.permission_overrides={'worker.deliver':False};db.commit()
    filtered=vehicle_view(client,worker_headers,pid,ids[0])
    assert not filtered['permissions']['submit']
    assert not any(row['id']==doc['id'] for row in filtered['documents'])
    version=response.json()['documents'][0]['latest_version']
    assert client.get('/api'+version['download_url'],headers=worker_headers).status_code in (403,404)
    other=inspection(vehicle_view(client,admin_headers,pid,ids[1]))
    assert upload(client,worker_headers,pid,[other['id']]).status_code==403
    assert inspection(vehicle_view(client,admin_headers,pid,ids[1]))['status']=='pending'


def test_preentry_still_allows_car_documents_without_matrix_progress(client,admin_headers):
    pid,ids=fleet(client,admin_headers)
    with SessionLocal() as db:
        db.get(Project,pid).status='ready';db.commit()
    doc=inspection(vehicle_view(client,admin_headers,pid,ids[0]))
    assert upload(client,admin_headers,pid,[doc['id']]).status_code==200
    assert client.get(f'/api/projects/{pid}/vehicle-progress',headers=admin_headers).json()['summary']['completed']==0
