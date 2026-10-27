"""T25 sessions use the live T26 family/file policy at every boundary."""
from app.db import SessionLocal
from app import models
from .test_confidential_documents_t26 import setup_project,policy
from .document_helpers import requirement,documents
from .test_resumable_uploads import start,chunk


def test_independent_policy_is_atomic_and_completed_retries_keep_current_scope(client,pm_headers,worker_headers):
    pid,users=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99',name='原子私密上传')
    session,body=start(client,pm_headers,pid,b'private before first commit',[doc['id']],confidential=True,
        confidential_user_ids=[users['worker1'],users['pm']])
    sid=session['id'];base=f'/api/projects/{pid}/uploads/{sid}'
    assert client.get(base,headers=pm_headers).headers['cache-control']=='private, no-store'
    assert chunk(client,pm_headers,pid,sid,0,b'private before first commit').status_code==200
    finished=client.post(base+'/finish',headers=pm_headers);assert finished.status_code==200,finished.text
    file=finished.json()['file'];assert file['confidential'] and file['access_version']==2 and file['confidential_user_ids']==[users['worker1']]
    assert client.get('/api'+file['download_url'],headers=worker_headers).content==b'private before first commit'
    updated=policy(client,pm_headers,pid,'file',file,[users['worker2']]);assert updated.status_code==200,updated.text
    repeated=client.post(base+'/finish',headers=pm_headers);assert repeated.status_code==200,repeated.text
    assert repeated.json()['file']['access_version']==updated.json()['access_version']
    assert repeated.json()['file']['confidential_user_ids']==[users['worker2']]
    resumed=client.post(f'/api/projects/{pid}/uploads',headers=pm_headers,json=body)
    assert resumed.status_code==200 and resumed.json()['state']=='finished',resumed.text
    assert client.get('/api'+file['download_url'],headers=worker_headers).status_code==403
    occupation=client.get(f'/api/projects/{pid}/storage',headers=worker_headers)
    assert occupation.status_code==200 and occupation.json()['bytes']==0 and occupation.json()['file_count']==0
    with SessionLocal() as db:
        assert db.query(models.Attachment).filter_by(project_id=pid).count()==1
        assert db.query(models.DocumentVersion).filter_by(project_document_id=doc['id']).count()==1
    # A readable public document must not leak an independently private file's
    # name/hash/cleaning proof through a nested DTO after the policy changes.
    row=next(row for row in documents(client,worker_headers,pid)['documents'] if row['id']==doc['id'])
    assert row['latest_version'] is None or row['latest_version'].get('restricted')
    for version in row['versions']:
        assert version['file'] is None and version['download_url']=='' and version['sha256'] is None
        assert version['filename']=='保密附件（未获查看权限）'
    assert file['filename'] not in str(row['versions'])


def test_private_family_revocation_rechecks_status_chunk_and_finish_without_evidence(client,pm_headers,worker_headers):
    pid,users=setup_project(client,pm_headers)
    doc=requirement(client,pm_headers,pid,code='6.99',name='会话家族撤权')
    session,_=start(client,worker_headers,pid,b'pending family bytes',[doc['id']])
    changed=policy(client,pm_headers,pid,'document',doc,[]);assert changed.status_code==200,changed.text
    base=f'/api/projects/{pid}/uploads/{session["id"]}'
    assert client.get(base,headers=worker_headers).status_code==403
    assert chunk(client,worker_headers,pid,session['id'],0,b'pending family bytes').status_code==403
    assert client.post(base+'/finish',headers=worker_headers).status_code==403
    with SessionLocal() as db:
        assert db.query(models.UploadChunk).count()==0 and db.query(models.DocumentVersion).count()==0
        assert db.query(models.Attachment).filter_by(project_id=pid).count()==0


def test_only_current_manager_may_keep_an_independent_private_session(client,pm_headers,admin_headers,worker_headers):
    pid,users=setup_project(client,pm_headers)
    session,_=start(client,pm_headers,pid,b'pending independent private',confidential=True,confidential_user_ids=[users['worker1']])
    from tests.lifecycle_helpers import second_pm, transfer_manager
    transferred=transfer_manager(client,admin_headers,pid,second_pm(client,admin_headers))
    assert transferred.status_code==200,transferred.text
    base=f'/api/projects/{pid}/uploads/{session["id"]}'
    # 原负责人移交后离开项目：续传会话不可读、不可续、不可完成（403/404 均为拒绝）。
    assert client.get(base,headers=pm_headers).status_code in (403,404)
    assert chunk(client,pm_headers,pid,session['id'],0,b'pending independent private').status_code in (403,404)
    assert client.post(base+'/finish',headers=pm_headers).status_code in (403,404)
    import hashlib
    failed=client.post(f'/api/projects/{pid}/uploads',headers=worker_headers,json={'client_uuid':'no-private-set-001','filename':'denied.bin',
        'size':1,'sha256':hashlib.sha256(b'x').hexdigest(),'document_ids':[],'confidential':True,'confidential_user_ids':[]})
    assert failed.status_code==403
    with SessionLocal() as db:assert db.query(models.UploadSession).count()==1 and db.query(models.Attachment).filter_by(project_id=pid).count()==0
