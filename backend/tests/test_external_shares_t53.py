"""Actual isolated HTTP boundaries: capability tokens never become business sessions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
import pytest
from app.db import SessionLocal
from app.models import ExternalShare, ExternalAccessLog, ChangeLog, Project, User, ProjectDocument, Attachment
from app.time_utils import utcnow
from tests.document_helpers import requirement, upload_documents, documents
from tests.test_confidential_documents_t26 import setup_project, policy


def share(client,headers,pid,**fields):
    response=client.post(f'/api/projects/{pid}/external-shares',headers=headers,
        json={'expires_at':(utcnow()+timedelta(days=7)).isoformat()+'Z',**fields})
    assert response.status_code==200,response.text
    return response.json()


def enter(client,row):
    response=client.post('/api/external/bootstrap',json={'token':row['token']})
    assert response.status_code==200,response.text
    return response.json(),{'Authorization':'Bearer '+response.json()['session_token']}


def test_default_only_progress_hash_only_and_external_identity_never_internal(client,pm_headers,admin_headers,worker_headers):
    pid,_=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,name='INTERNAL-ONLY-DOC')
    upload_documents(client,pm_headers,pid,[doc['id']],content=b'internal original')
    row=share(client,pm_headers,pid)
    assert row['scopes']==['project_progress','vehicle_progress']
    assert 'token_hash' not in row and row['token']
    payload,headers=enter(client,row)
    view=payload['view']
    assert set(view)=={'share_id','project_name','scopes','expires_at','project_progress','vehicle_progress'}
    assert 'INTERNAL-ONLY-DOC' not in json.dumps(view)
    assert 'members' not in json.dumps(view) and 'done_by' not in json.dumps(view)
    assert client.get('/api/projects/'+pid,headers=headers).status_code==401
    assert client.post('/api/projects',headers=headers,json={'name':'cannot-write'}).status_code==401
    assert client.get('/api/external/view',headers=pm_headers).status_code==401
    assert client.get('/api/external/view',headers={'Authorization':'Bearer '+row['token']}).status_code==401
    assert client.post('/api/external/bootstrap',params={'token':row['token']}).status_code==401
    listed=client.get(f'/api/projects/{pid}/external-shares',headers=pm_headers)
    assert listed.status_code==200 and row['token'] not in listed.text and 'token_hash' not in listed.text
    for rejected in (admin_headers,worker_headers):
        assert client.get(f'/api/projects/{pid}/external-shares',headers=rejected).status_code==403
        assert client.post(f'/api/projects/{pid}/external-shares',headers=rejected,json={'expires_at':row['expires_at']}).status_code==403
    with SessionLocal() as db:
        persisted=db.get(ExternalShare,row['id'])
        assert persisted.token_hash==hashlib.sha256(row['token'].encode()).hexdigest()
        audit=' '.join(str(r.__dict__) for r in db.query(ChangeLog).filter_by(project_id=pid))
        assert row['token'] not in audit and payload['session_token'] not in audit
        assert db.query(ChangeLog).filter_by(project_id=pid,action='share_create').count()==1


def test_explicit_range_latest_only_cross_document_and_project_ids_denied(client,pm_headers):
    pid,_=setup_project(client,pm_headers)
    a=requirement(client,pm_headers,pid,code='6.98',name='EXPLICIT-ALLOWED')
    b=requirement(client,pm_headers,pid,code='6.99',name='NOT-SELECTED')
    old=upload_documents(client,pm_headers,pid,[a['id']],content=b'old')
    newest=upload_documents(client,pm_headers,pid,[a['id']],content=b'latest')['documents'][0]['latest_version']
    other=upload_documents(client,pm_headers,pid,[b['id']],content=b'not selected')['documents'][0]['latest_version']
    other_pid,_=setup_project(client,pm_headers)
    foreign=requirement(client,pm_headers,other_pid)
    foreign_version=upload_documents(client,pm_headers,other_pid,[foreign['id']])['documents'][0]['latest_version']
    row=share(client,pm_headers,pid,scopes=['selected_documents'],document_ids=[a['id']])
    payload,headers=enter(client,row)
    assert len(payload['view']['documents'])==1 and payload['view']['documents'][0]['name']=='EXPLICIT-ALLOWED'
    base='/api/external/documents/'
    downloaded=client.get(base+a['id']+'/versions/'+newest['id']+'/download',headers=headers)
    assert downloaded.content==b'latest'
    assert downloaded.headers['cache-control']=='private, no-store' and downloaded.headers['referrer-policy']=='no-referrer'
    assert downloaded.headers['content-disposition'].startswith('attachment;')
    for did,vid in ((a['id'],old['documents'][0]['latest_version']['id']),(b['id'],other['id']),
                    (foreign['id'],foreign_version['id']),(a['id'],foreign_version['id'])):
        assert client.get(base+did+'/versions/'+vid+'/download',headers=headers).status_code==404
    # The only project comes from the grant, never caller-controlled query data.
    assert client.get('/api/external/view',headers=headers,params={'project_id':other_pid}).json()['project_name']==payload['view']['project_name']
    assert client.get(f'/api/external/projects/{other_pid}',headers=headers).status_code==404


def test_confidentiality_and_shared_original_intersection_rechecked_after_creation(client,pm_headers,admin_headers):
    pid,_=setup_project(client,pm_headers)
    a=requirement(client,pm_headers,pid,code='6.98',name='PUBLIC-NAME')
    b=requirement(client,pm_headers,pid,code='6.99',name='SHARED-PRIVATE')
    upload=upload_documents(client,pm_headers,pid,[a['id'],b['id']],content=b'same original')
    a,b=upload['documents']
    row=share(client,pm_headers,pid,scopes=['selected_documents'],document_ids=[a['id']])
    _,headers=enter(client,row)
    assert policy(client,pm_headers,pid,'document',b).status_code==200
    current=client.get('/api/external/view',headers=headers)
    assert current.status_code==200 and current.json()['documents']==[]
    assert 'SHARED-PRIVATE' not in current.text and 'PUBLIC-NAME' not in current.text
    assert client.get('/api/external/documents/'+a['id']+'/versions/'+a['latest_version']['id']+'/download',headers=headers).status_code==404
    assert client.post(f'/api/projects/{pid}/external-shares',headers=pm_headers,json={
        'expires_at':row['expires_at'],'scopes':['selected_documents'],'document_ids':[b['id']]}).status_code==400
    # A family-level default must not be bypassed through an inconsistent old row.
    with SessionLocal() as db:
        from app.models import ProjectDocumentDefinition
        asset=db.get(Attachment,upload['file']['id']);asset.confidential=False
        for doc in db.query(ProjectDocument).filter(ProjectDocument.id.in_([a['id'],b['id']])):doc.confidential=False;doc.external_never_visible=False
        db.get(ProjectDocumentDefinition,a['definition_id']).confidential_default=True;db.commit()
    assert client.get('/api/external/view',headers=headers).json()['documents']==[]
    assert client.get('/api/external/view',headers=admin_headers).status_code==401


@pytest.mark.parametrize('kind',['expiry','revoke','deleted','owner_disabled','owner_transfer','owner_permission'])
def test_current_grant_revocation_and_owner_changes_invalidate_existing_sessions(client,pm_headers,kind):
    pid,users=setup_project(client,pm_headers);row=share(client,pm_headers,pid)
    _,headers=enter(client,row)
    if kind=='revoke':
        response=client.post(f'/api/projects/{pid}/external-shares/{row["id"]}/revoke',headers=pm_headers,json={'version':row['version']})
        assert response.status_code==200,response.text
        assert client.post(f'/api/projects/{pid}/external-shares/{row["id"]}/revoke',headers=pm_headers,json={'version':row['version']}).status_code==409
    else:
        with SessionLocal() as db:
            project=db.get(Project,pid);owner=db.get(User,project.manager)
            if kind=='expiry':db.get(ExternalShare,row['id']).expires_at=utcnow()-timedelta(seconds=1)
            if kind=='deleted':project.deleted_at=utcnow()
            if kind=='owner_disabled':owner.is_active=False
            if kind=='owner_transfer':project.manager=users['admin']
            if kind=='owner_permission':owner.permission_overrides={'project.update':False}
            db.commit()
    assert client.get('/api/external/view',headers=headers).status_code==401
    assert client.post('/api/external/bootstrap',json={'token':row['token']}).status_code==401


def test_logs_record_peer_time_content_and_failures_without_credentials(client,pm_headers):
    pid,_=setup_project(client,pm_headers);doc=requirement(client,pm_headers,pid)
    current=upload_documents(client,pm_headers,pid,[doc['id']])['documents'][0]
    row=share(client,pm_headers,pid,scopes=['selected_documents'],document_ids=[doc['id']]);payload,headers=enter(client,row)
    headers['X-Forwarded-For']='198.51.100.22'
    assert client.get('/api/external/view',headers=headers).status_code==200
    url='/api/external/documents/'+doc['id']+'/versions/'+current['latest_version']['id']+'/download'
    assert client.get(url,headers=headers).status_code==200
    assert client.get(url.replace(doc['id'],'missing'),headers=headers).status_code==404
    logged=client.get(f'/api/projects/{pid}/external-shares/{row["id"]}/access',headers=pm_headers)
    assert logged.status_code==200
    rows=logged.json();assert {r['action'] for r in rows}=={'bootstrap','view','download'}
    assert all(r['ip']=='testclient' and r['time'] for r in rows)
    assert any(r['resource_id']==doc['id'] and r['status_code']==200 for r in rows)
    assert any(r['status_code']==404 for r in rows)
    assert row['token'] not in logged.text and payload['session_token'] not in logged.text
    assert logged.headers['cache-control']=='private, no-store'
    from app.services.project_deletion import project_backup_snapshot
    from app.services.project_retention import project_retention_snapshot
    with SessionLocal() as db:
        project=db.get(Project,pid)
        private=project_backup_snapshot(db,project)
        assert private['records']['external_shares'][0]['token_hash']==hashlib.sha256(row['token'].encode()).hexdigest()
        assert len(private['records']['external_access_logs'])==4
        assert 'external_shares' not in project_retention_snapshot(db,project)['records']


def test_scopes_expiry_and_foreign_selection_are_validated_without_side_effects(client,pm_headers):
    pid,_=setup_project(client,pm_headers);other,_=setup_project(client,pm_headers);foreign=requirement(client,pm_headers,other)
    endpoint=f'/api/projects/{pid}/external-shares'
    good={'expires_at':(utcnow()+timedelta(days=1)).isoformat()+'Z'}
    for invalid in ({'scopes':[]},{'scopes':['project_progress','project_progress']},{'scopes':['unknown']},
                    {'scopes':['selected_documents'],'document_ids':[foreign['id']]},{'scopes':['selected_documents']},
                    {'document_ids':[foreign['id']]},{'expires_at':'2000-01-01T00:00:00Z'},
                    {'expires_at':(utcnow()+timedelta(days=367)).isoformat()+'Z'},{'expires_at':'2026-12-01T00:00:00'}):
        assert client.post(endpoint,headers=pm_headers,json={**good,**invalid}).status_code in (400,422)
    with SessionLocal() as db:assert db.query(ExternalShare).count()==0
    for raw in (b'',b'{',b'[]',b'{"token":"fake"}',b'x'*513):
        response=client.post('/api/external/bootstrap',content=raw)
        assert response.status_code==401 and response.headers['cache-control']=='private, no-store'
        assert 'fake' not in response.text


def test_simultaneous_revocation_has_one_winner_and_archived_links_can_be_revoked(client,pm_headers):
    pid,_=setup_project(client,pm_headers);row=share(client,pm_headers,pid)
    with SessionLocal() as db:db.get(Project,pid).status='archived';db.commit()
    def revoke():return client.post(f'/api/projects/{pid}/external-shares/{row["id"]}/revoke',headers=pm_headers,json={'version':row['version']}).status_code
    with ThreadPoolExecutor(max_workers=2) as workers:assert sorted(workers.map(lambda _:revoke(),range(2)))==[200,409]
    with SessionLocal() as db:assert db.query(ChangeLog).filter_by(project_id=pid,action='share_revoke').count()==1


def test_fresh_actor_and_revocation_are_rechecked_after_project_lock(client,pm_headers,monkeypatch):
    from app.services import external_shares as service
    from sqlalchemy import update
    pid,people=setup_project(client,pm_headers);row=share(client,pm_headers,pid)
    _,headers=enter(client,row)
    original=service.lock_record
    def revoke_before_refresh(db,project,**kwargs):
        original(db,project,**kwargs)
        db.execute(update(ExternalShare).where(ExternalShare.id==row['id']).values(revoked_at=utcnow()).execution_options(synchronize_session=False))
    monkeypatch.setattr(service,'lock_record',revoke_before_refresh)
    assert client.get('/api/external/view',headers=headers).status_code==401
    with SessionLocal() as db:assert db.query(ExternalAccessLog).filter_by(share_id=row['id'],status_code=401).count()==1
    def stale_actor(db,project,**kwargs):
        original(db,project,**kwargs)
        db.execute(update(User).where(User.id==people['pm']).values(token_version=User.token_version+1).execution_options(synchronize_session=False))
    monkeypatch.setattr(service,'lock_record',stale_actor)
    response=client.post(f'/api/projects/{pid}/external-shares',headers=pm_headers,json={'expires_at':(utcnow()+timedelta(days=1)).isoformat()+'Z'})
    assert response.status_code==401
    with SessionLocal() as db:assert db.query(ExternalShare).count()==1


def test_signoff_delivery_ranges_and_independent_file_policy_never_include_secrets(client,pm_headers):
    pid,_=setup_project(client,pm_headers)
    from tests.lifecycle_helpers import enter_execution
    enter_execution(client,pm_headers,pid)  # 6.11 现场周资料从现场实施开始生成
    rows=documents(client,pm_headers,pid)['documents']
    sign=next(row for row in rows if row['code']=='6.10.2')
    delivery=next(row for row in rows if row['stage_key']=='8')
    private=next(row for row in rows if row['code']=='6.11.6a')
    sign=upload_documents(client,pm_headers,pid,[sign['id']])['documents'][0]
    upload_documents(client,pm_headers,pid,[delivery['id']])
    row=share(client,pm_headers,pid,scopes=['signoffs','delivery_documents'])
    payload,headers=enter(client,row)
    ids={item['id'] for item in payload['view']['documents']}
    assert sign['id'] in ids and delivery['id'] in ids and private['id'] not in ids
    assert all(item['code'] in ('6.10.1','6.10.2','6.10.3','6.10.4') or next(r for r in rows if r['id']==item['id'])['stage_key'] in ('7','8') for item in payload['view']['documents'])
    file=sign['latest_version']['file']
    assert policy(client,pm_headers,pid,'file',file).status_code==200
    assert sign['id'] not in {item['id'] for item in client.get('/api/external/view',headers=headers).json()['documents']}
    # Even an explicitly selected raw ID cannot make the canonical private family public.
    response=client.post(f'/api/projects/{pid}/external-shares',headers=pm_headers,json={
        'expires_at':row['expires_at'],'scopes':['selected_documents'],'document_ids':[private['id']]})
    assert response.status_code==400


def test_encrypted_permanent_backup_preserves_share_and_logs_before_fk_cascade(client,pm_headers,admin_headers,tmp_path):
    from tests.test_project_recycle_bin import _delete
    from tests.test_retention_unification import prepare,purge
    from app.services.project_deletion import backup_zip
    from app.services import backup_crypto as codec
    pid,_=setup_project(client,pm_headers);row=share(client,pm_headers,pid);enter(client,row)
    current=client.get('/api/projects/'+pid,headers=pm_headers).json()
    assert _delete(client,pm_headers,current).status_code==200
    recycled=client.get('/api/project-recycle-bin/projects/'+pid,headers=admin_headers).json()
    response=prepare(client,admin_headers,recycled);assert response.status_code==200,response.text
    receipt=response.json();download=client.get('/api/project-recycle-bin/backups/'+receipt['backup_id'],headers=admin_headers)
    assert download.status_code==200
    path=tmp_path/'external-private.agvenc';path.write_bytes(download.content)
    assert codec.is_encrypted(path)
    with backup_zip(path) as bundle:
        snapshot=json.loads(bundle.read('project-backup.json'))
        records=snapshot['records']
        assert records['external_shares'][0]['id']==row['id']
        assert records['external_shares'][0]['token_hash']==hashlib.sha256(row['token'].encode()).hexdigest()
        assert records['external_access_logs'][0]['share_id']==row['id']
        assert row['token'] not in json.dumps(snapshot)
    result=purge(client,admin_headers,recycled,receipt);assert result.status_code==200,result.text
    with SessionLocal() as db:
        assert db.get(Project,pid) is None and db.get(ExternalShare,row['id']) is None
        assert db.query(ExternalAccessLog).filter_by(project_id=pid).count()==0


def test_project_and_vehicle_progress_use_real_distinct_canonical_totals_without_work_text(client,pm_headers):
    from tests.test_vehicle_progress import setup_fleet
    from app.models import Phase,Module,Task
    from app.services.progress import project_progress_tree
    pid,_=setup_fleet(client,pm_headers,1)
    with SessionLocal() as db:
        phase=Phase(project_id=pid,name='INTERNAL-PHASE',sort_order=1);db.add(phase);db.flush()
        module=Module(project_id=pid,phase_id=phase.id,name='INTERNAL-WORK');db.add(module);db.flush()
        db.add(Task(project_id=pid,module_id=module.id,name='INTERNAL-TASK',quantity_type='fixed',unit='米',target_quantity=1000,manually_completed=True))
        db.commit();canonical=project_progress_tree(db,pid)
        assert canonical['completed']==1 and canonical['percent']>0
    payload,_=enter(client,share(client,pm_headers,pid))
    assert payload['view']['project_progress']['percent']==canonical['percent']
    assert payload['view']['project_progress']['completed']==1
    assert payload['view']['vehicle_progress']['summary']['percent']==0
    assert 'INTERNAL-' not in json.dumps(payload['view'])
