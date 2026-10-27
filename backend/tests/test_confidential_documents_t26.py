"""T26 public API: owner-defined scope, shared evidence, no role/upload bypass."""
import json

from app.db import SessionLocal
from app.models import User, ChangeLog, Project, ProjectDocument, ProjectDocumentDefinition, ProjectEvent
from tests.document_helpers import requirement, upload_documents, documents


def setup_project(client, pm_headers):
    with SessionLocal() as db:
        people={u.username:u.id for u in db.query(User)}
    response=client.post('/api/projects',headers=pm_headers,json={'name':'T26隔离项目','start_date':'2026-01-01','end_date':'2026-12-31',
        'technical_manager_id':people['worker2']})
    assert response.status_code==200,response.text
    created=response.json()
    added=client.put('/api/projects/'+created['id'],headers=pm_headers,json={
        'members':[people['pm'],people['worker1'],people['worker2']], 'version':created['version']})
    assert added.status_code==200,added.text
    return created['id'],people


def policy(client,headers,pid,kind,row,people=(),confidential=True):
    identity=row['id']
    path=f'/api/projects/{pid}/documents/'+('files/' if kind=='file' else 'requirements/' if kind=='definition' else '')+identity+'/confidentiality'
    return client.put(path,headers=headers,json={'confidential':confidential,'confidential_user_ids':list(people),
        'version':row['version'] if kind=='document' else row['access_version']})


def test_only_owner_or_explicit_people_can_read_no_admin_technical_or_submitter_bypass(client,pm_headers,admin_headers,worker_headers):
    pid,users=setup_project(client,pm_headers)
    worker2=client.post('/api/auth/login',json={'username':'worker2','password':'worker123'}).json()
    technical={'Authorization':'Bearer '+worker2['access_token']}
    doc=requirement(client,pm_headers,pid,code='6.99',name='T26保密内容')
    uploaded=upload_documents(client,technical,pid,[doc['id']],content=b'only explicit readers',name='T26-secret.txt')
    doc=uploaded['documents'][0]
    changed=policy(client,pm_headers,pid,'document',doc,[users['worker1']])
    assert changed.status_code==200,changed.text
    assert changed.headers['cache-control']=='private, no-store'
    row=changed.json();url='/api'+row['versions'][0]['download_url'];fid=uploaded['file']['id']
    assert client.get(url,headers=pm_headers).content==b'only explicit readers'
    assert client.get(url,headers=worker_headers).status_code==200
    for denied in (admin_headers,technical):
        assert row['id'] not in {r['id'] for r in documents(client,denied,pid)['documents']}
        assert client.get(url,headers=denied).status_code==403
        assert client.get(f'/api/files/{fid}/download',headers=denied).status_code==403
    assert policy(client,technical,pid,'document',row,[users['worker2']]).status_code==403
    assert policy(client,admin_headers,pid,'document',row,[users['admin']]).status_code==403
    assert policy(client,pm_headers,pid,'document',doc,[]).status_code==409
    # A designation adds visibility; existing C_PLAN still governs metadata,
    # while neither path delegates the ability to rewrite the private scope.
    shared=policy(client,pm_headers,pid,'document',row,[users['worker1'],users['worker2']])
    assert shared.status_code==200,shared.text
    state=documents(client,technical,pid)
    definition=next(r for r in state['definitions'] if r['id']==doc['definition_id'])
    from app.services.document_requirements import RequirementInput
    rule={key:value for key,value in definition.items() if key in RequirementInput.model_fields}
    assert client.put(f'/api/projects/{pid}/documents/requirements/{definition["id"]}',headers=technical,json={**rule,'note':'获指定且有计划权限的人员可维护说明'}).status_code==200
    assert client.put(f'/api/projects/{pid}/documents/requirements/{definition["id"]}',headers=technical,json={**rule,'external_never_visible':False}).status_code==409
    assert policy(client,technical,pid,'document',shared.json(),[users['worker2']]).status_code==403
    # Every successful authorized download and metadata read is an audit event.
    with SessionLocal() as db:
        assert db.query(ChangeLog).filter(ChangeLog.project_id==pid,ChangeLog.action=='confidential_dl').count()>=2
        assert db.query(ChangeLog).filter(ChangeLog.project_id==pid,ChangeLog.action=='confidential_view').count()>=1


def test_shared_file_requires_all_document_scopes_and_its_explicit_policy(client,pm_headers,worker_headers):
    pid,users=setup_project(client,pm_headers)
    a=requirement(client,pm_headers,pid,code='6.98',name='共享保密A')
    b=requirement(client,pm_headers,pid,code='6.99',name='共享保密B')
    uploaded=upload_documents(client,pm_headers,pid,[a['id'],b['id']],content=b'shared')
    a,b=uploaded['documents']
    a=policy(client,pm_headers,pid,'document',a,[users['worker1']]).json()
    b=policy(client,pm_headers,pid,'document',b,[users['worker2']]).json()
    url=f'/api/files/{uploaded["file"]["id"]}/download'
    assert client.get(url,headers=worker_headers).status_code==403
    b=policy(client,pm_headers,pid,'document',b,[users['worker1']]).json()
    assert client.get(url,headers=worker_headers).content==b'shared'
    file=next(row for row in client.get(f'/api/projects/{pid}/documents/files',headers=pm_headers).json() if row['id']==uploaded['file']['id'])
    changed=policy(client,pm_headers,pid,'file',file,[users['worker2']])
    assert changed.status_code==200,changed.text
    assert client.get(url,headers=worker_headers).status_code==403
    assert client.get(url,headers=pm_headers).status_code==200


def test_plain_exports_hide_private_content_and_owner_exports_are_audited(client,pm_headers,admin_headers):
    import io
    from zipfile import ZipFile
    from openpyxl import load_workbook
    pid,_=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99',name='T26-PRIVATE-TITLE')
    uploaded=upload_documents(client,pm_headers,pid,[doc['id']],content=b'T26-PRIVATE-BYTES',name='T26-PRIVATE-FILE.txt')
    assert policy(client,pm_headers,pid,'document',uploaded['documents'][0]).status_code==200
    snapshot=client.get(f'/api/projects/{pid}/export/json',headers=admin_headers)
    assert snapshot.status_code==200
    assert 'T26-PRIVATE' not in snapshot.text
    assert 'T26-PRIVATE' not in client.get(f'/api/projects/{pid}/logs',headers=admin_headers).text
    excel=client.get(f'/api/projects/{pid}/export/excel',headers=admin_headers)
    assert excel.status_code==200
    wb=load_workbook(io.BytesIO(excel.content));assert not any('T26-PRIVATE' in str(c.value) for s in wb for rows in s for c in rows)
    package=client.get(f'/api/projects/{pid}/export/package',headers=admin_headers)
    assert package.status_code==200
    with ZipFile(io.BytesIO(package.content)) as z:
        assert all('T26-PRIVATE' not in n for n in z.namelist())
        assert 'T26-PRIVATE' not in z.read('项目备份.json').decode()


def test_family_policy_covers_history_future_instances_and_current_owner_transfer(client,pm_headers,admin_headers,worker_headers):
    from app.services import project_documents as docs
    pid,users=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99',name='家族全部历史')
    first=upload_documents(client,pm_headers,pid,[doc['id']],content=b'old',name='old.txt')
    second=upload_documents(client,pm_headers,pid,[doc['id']],content=b'new',name='new.txt')
    changed=policy(client,pm_headers,pid,'document',second['documents'][0],[users['worker1'],users['pm']])
    assert changed.status_code==200,changed.text
    assert users['pm'] not in changed.json()['confidential_user_ids']
    for version in changed.json()['versions']:
        assert client.get('/api'+version['download_url'],headers=admin_headers).status_code==403
        assert client.get('/api'+version['download_url'],headers=worker_headers).status_code==200
    with SessionLocal() as db:
        definition=db.get(ProjectDocumentDefinition,doc['definition_id'])
        assert definition.confidential_default and definition.confidential_user_ids==[users['worker1']]
        definition.timing_type='weekly';definition.timing_weekday=5
        future=docs.instantiate(db,db.get(Project,pid),definition,period_key='2027-W01')
        assert future.confidential and future.confidential_user_ids==[users['worker1']]
        db.commit()
    current=client.get('/api/projects/'+pid,headers=pm_headers).json()
    changed_owner=client.put('/api/projects/'+pid,headers=admin_headers,json={'manager_id':users['admin'],'version':current['version']})
    assert changed_owner.status_code==200,changed_owner.text
    file_url=f'/api/files/{first["file"]["id"]}/download'
    assert client.get(file_url,headers=admin_headers).status_code==200
    assert client.get(file_url,headers=pm_headers).status_code==403
    assert client.get(file_url,headers=worker_headers).status_code==200


def test_simultaneous_policy_edits_have_one_winner_and_refresh_stale_actor(client,pm_headers):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    import pytest
    from app.services import project_documents as docs
    pid,users=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99')
    def change(identity):return policy(client,pm_headers,pid,'document',doc,[identity]).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change,[users['worker1'],users['worker2']]))==[200,409]
    with SessionLocal() as stale:
        actor=stale.get(User,users['pm'])
        with SessionLocal() as other:
            other.get(User,actor.id).token_version+=1;other.commit()
        with pytest.raises(HTTPException) as error:docs.writable(stale,pid,actor,'project.manage_plan')
        assert error.value.status_code==401
        stale.rollback()
    with SessionLocal() as stale:
        actor=stale.get(User,users['pm'])
        with SessionLocal() as other:
            other.get(User,actor.id).is_active=False;other.commit()
        with pytest.raises(HTTPException) as error:docs.writable(stale,pid,actor,'project.manage_plan')
        assert error.value.status_code==401
        stale.rollback()


def test_agent_and_mcp_use_same_scope_and_external_never_reads(client,pm_headers,admin_headers):
    from .test_agent_api import token,call,mcp_call
    from app.services import project_documents as docs
    from types import SimpleNamespace
    pid,users=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99',name='T26-AGENT-PRIVATE')
    upload=upload_documents(client,pm_headers,pid,[doc['id']],content=b'private',name='T26-AGENT-PRIVATE.txt')
    assert policy(client,pm_headers,pid,'document',upload['documents'][0]).status_code==200
    _,agent=token(client,admin_headers,scopes=['projects:read','files:read'])
    result=call(client,agent,'documents_read',project_id=pid)
    assert result.status_code==200 and 'T26-AGENT-PRIVATE' not in result.text
    result=mcp_call(client,agent,'tools/call',{'name':'project_files','arguments':{'project_id':pid}})
    assert result.status_code==200 and 'T26-AGENT-PRIVATE' not in result.text
    with SessionLocal() as db:
        project=db.get(Project,pid);row=db.get(ProjectDocument,doc['id'])
        external=SimpleNamespace(id=project.manager,role='external',is_active=True)
        assert not docs.can_read_document(external,project,row)
        from app.models import Attachment
        assert not docs.can_read_file(external,project,db.get(Attachment,upload['file']['id']))


def test_private_encrypted_snapshot_keeps_originals_while_legacy_plain_reader_requires_frozen_scope(client,pm_headers,admin_headers,tmp_path):
    from app.services.project_retention import project_retention_snapshot
    from app.models import ProjectArchive
    from app.routers.archives import _archive_checksum
    from app.time_utils import utcnow
    pid,users=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99',name='T26-RETAINED-PRIVATE')
    upload=upload_documents(client,pm_headers,pid,[doc['id']],content=b'preserved original',name='retained-secret.txt')
    assert policy(client,pm_headers,pid,'document',upload['documents'][0],[users['worker1']]).status_code==200
    with SessionLocal() as db:
        snapshot=project_retention_snapshot(db,db.get(Project,pid))
        assert next(r for r in snapshot['records']['project_documents'] if r['id']==doc['id'])['confidential_user_ids']==[users['worker1']]
        assert any(r['filename']=='retained-secret.txt' for r in snapshot['records']['attachments'])
        archive=ProjectArchive(project_id=pid,project_name='保留原文',snapshot=snapshot,change_logs=[],actor_ids=[],purged_at=utcnow(),checksum='')
        archive.checksum=_archive_checksum(archive);checksum=archive.checksum;db.add(archive);db.commit()
        stored=next(r['stored_name'] for r in snapshot['records']['attachments'] if r['id']==upload['file']['id'])
    assert client.get('/api/archives/projects/'+pid,headers=admin_headers).status_code==403
    assert client.get(f'/api/archives/projects/{pid}/files/{stored}',headers=admin_headers).status_code==403
    assert client.get('/api/archives/projects/'+pid+'/verify',headers=admin_headers).json()['match']
    assert client.get('/api/archives/projects',headers=admin_headers).status_code==200
    with SessionLocal() as db:assert db.query(ProjectArchive).filter_by(project_id=pid).one().checksum==checksum
    from .test_project_recycle_bin import _delete
    from app.services.project_deletion import backup_zip
    from app.services import backup_crypto as codec
    current=client.get('/api/projects/'+pid,headers=pm_headers).json()
    assert _delete(client,pm_headers,current).status_code==200
    recycled=client.get('/api/project-recycle-bin/projects/'+pid,headers=pm_headers).json()
    download=client.get(f'/api/project-recycle-bin/projects/{pid}/backup',params={'deletion_id':recycled['deletion_id']},headers=pm_headers)
    assert download.status_code==200
    encrypted=tmp_path/'private-project.agvenc';encrypted.write_bytes(download.content)
    assert codec.is_encrypted(encrypted)
    with backup_zip(encrypted) as bundle:
        private=json.loads(bundle.read('project-backup.json'))
        assert next(row for row in private['records']['project_documents'] if row['id']==doc['id'])['confidential_user_ids']==[users['worker1']]
        file=next(row for row in private['binary_files']['manifest'] if row['filename']=='retained-secret.txt')
        assert bundle.read(file['path'])==b'preserved original'


def test_project_blank_uses_family_scope_while_global_unfilled_template_stays_public(client,pm_headers,admin_headers,worker_headers):
    base='/api/templates/default/document-requirements'
    rule=next(row for row in client.get(base,headers=admin_headers).json() if row['code']=='6.11.6b')
    global_url=base+'/'+rule['id']+'/blank-file'
    response=client.post(global_url,headers=admin_headers,files={'file':('unfilled-position.txt',b'empty form: password manager location','text/plain')})
    assert response.status_code==200,response.text
    pid,users=setup_project(client,pm_headers)
    state=documents(client,pm_headers,pid)
    definition=next(row for row in state['definitions'] if row['code']=='6.11.6b')
    assert definition['confidential_default'] and not definition['confidential_user_ids']
    project_url=f'/api/projects/{pid}/documents/requirements/{definition["id"]}/blank-file'
    assert client.get(project_url,headers=admin_headers).status_code==403
    assert client.get(project_url,headers=worker_headers).status_code==403
    assert client.get(project_url,headers=pm_headers).status_code==200
    changed=policy(client,pm_headers,pid,'definition',definition,[users['worker1']])
    assert changed.status_code==200,changed.text
    assert client.get(project_url,headers=worker_headers).content==b'empty form: password manager location'
    assert client.get(global_url,headers=admin_headers).status_code==200


def test_completion_review_real_status_and_future_blockers_never_reveal_private_titles(client,pm_headers,admin_headers):
    from app.services.project_documents import filter_blockers,redact_document_text
    from app.services.lifecycle_gates import Blocker,check_transition
    pid,_=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99',name='T26-SECRET-GATE-TITLE')
    assert policy(client,pm_headers,pid,'document',doc).status_code==200
    with SessionLocal() as db:
        project=db.get(Project,pid);project.status='acceptance';db.commit()
        admin=db.query(User).filter_by(username='admin').one()
        raw=check_transition(db,project,'completed')
        assert any('T26-SECRET-GATE-TITLE' in row.message for row in raw)
        filtered=filter_blockers(db,project,admin,[*raw,Blocker('kickoff_documents','4.1 T26-SECRET-GATE-TITLE','/documents'),
            Blocker('signature_documents','到货签收单、T26-SECRET-GATE-TITLE','/documents')])
        assert all('T26-SECRET-GATE-TITLE' not in row.message for row in filtered)
        assert '到货签收单' in filtered[-1].message
        public=Blocker('documents','仍需提交公开资料：4.1 公开责任书','/documents')
        assert filter_blockers(db,project,admin,[public])==[public]
        assert 'T26-SECRET-GATE-TITLE' not in redact_document_text(db,project,admin,'待交：T26-SECRET-GATE-TITLE')
        assert any('T26-SECRET-GATE-TITLE' in row.message for row in raw)  # Pure source result was not mutated.
    review=client.get(f'/api/projects/{pid}/completion-review',headers=admin_headers)
    assert review.status_code==200 and 'T26-SECRET-GATE-TITLE' not in review.text
    rejected=client.post(f'/api/projects/{pid}/status',headers=admin_headers,json={'status':'completed'})
    assert rejected.status_code==400 and 'T26-SECRET-GATE-TITLE' not in rejected.text


def test_independent_private_upload_is_atomic_and_ordinary_members_cannot_assign_acl(client,pm_headers,admin_headers,worker_headers):
    pid,users=setup_project(client,pm_headers)
    url=f'/api/projects/{pid}/documents/files'
    data={'confidential':'true','confidential_user_ids':json.dumps([users['worker1']])}
    response=client.post(url,headers=pm_headers,data=data,files={'file':('private-at-first-commit.txt',b'private from birth','text/plain')})
    assert response.status_code==200,response.text
    file=response.json()['file'];assert file['confidential'] and file['confidential_explicit'] and file['access_version']==2
    assert client.get('/api/files/'+file['id']+'/download',headers=admin_headers).status_code==403
    assert client.get('/api/files/'+file['id']+'/download',headers=worker_headers).content==b'private from birth'
    rejected=client.post(url,headers=worker_headers,data=data,files={'file':('cannot-self-authorize.txt',b'no','text/plain')})
    assert rejected.status_code==403
    assert {row['id'] for row in client.get(url,headers=pm_headers).json()}=={file['id']}
    assert client.post(url,headers=pm_headers,data={'confidential_user_ids':'{}'},files={'file':('bad.txt',b'no','text/plain')}).status_code==400


def test_private_upload_preserves_explicit_signoff_date_and_vehicle_filter_contract(client,pm_headers,admin_headers):
    from tests.document_helpers import documents
    pid,_=setup_project(client,pm_headers)
    row=next(item for item in documents(client,pm_headers,pid)['documents'] if item['code']=='6.10.2')
    response=client.post(f'/api/projects/{pid}/documents/files',headers=pm_headers,
        data={'document_ids':json.dumps([row['id']]),'milestone_dates':json.dumps({'commissioning_done':'2026-01-02'}),
              'confidential':'true','confidential_user_ids':'[]'},files={'file':('private-signoff.txt',b'private original','text/plain')})
    assert response.status_code==200,response.text
    current=response.json()['documents'][0]
    assert current['versions'][0]['file']['confidential_explicit']
    assert client.get('/api'+current['versions'][0]['download_url'],headers=admin_headers).status_code==403
    with SessionLocal() as db:
        event=db.query(ProjectEvent).filter_by(project_id=pid,event_key='commissioning_done').one()
        assert event.actual_date.isoformat()=='2026-01-02' and event.actual_at is None
        assert event.actual_source['attachment_id']==response.json()['file']['id']
    invalid=client.get(f'/api/projects/{pid}/documents',headers=pm_headers,params={'vehicle_unit_id':'not-a-real-unit'})
    assert invalid.status_code==404
