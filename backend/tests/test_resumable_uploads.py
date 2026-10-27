"""The small-file CI protocol is identical to the real 2-GiB streaming drill."""
import hashlib
import pytest
from app.db import SessionLocal
from app.models import Attachment,DocumentVersion,ProjectDocument,UploadSession,User
from app import config
from .test_project_documents import create,view


def start(client,headers,pid,data,ids=(),**fields):
    body={'client_uuid':'stable-file-intent-001','filename':'原件.bin','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
        'document_ids':list(ids),**fields}
    result=client.post(f'/api/projects/{pid}/uploads',headers=headers,json=body)
    assert result.status_code==200,result.text
    return result.json(),body


def chunk(client,headers,pid,sid,index,data):
    return client.put(f'/api/projects/{pid}/uploads/{sid}/chunks/{index}',headers={**headers,
        'Content-Type':'application/octet-stream','X-Chunk-SHA256':hashlib.sha256(data).hexdigest()},content=data)


def test_interrupted_upload_reuses_intent_chunks_and_finish_without_duplicate_versions(client,admin_headers,monkeypatch):
    monkeypatch.setattr(config,'UPLOAD_CHUNK_SIZE',8)
    pid=create(client,admin_headers)['id'];ids=[row['id'] for row in view(client,admin_headers,pid)['documents'][:2]]
    data=b'0123456789abcdefLAST';session,body=start(client,admin_headers,pid,data,ids)
    sid=session['id'];base=f'/api/projects/{pid}/uploads/{sid}'
    assert chunk(client,admin_headers,pid,sid,0,data[:8]).status_code==200
    resumed=client.post(f'/api/projects/{pid}/uploads',headers=admin_headers,json=body)
    assert resumed.json()['id']==sid and [item['index'] for item in resumed.json()['received']]==[0]
    assert client.post(base+'/finish',headers=admin_headers).status_code==409
    assert chunk(client,admin_headers,pid,sid,0,data[:8]).status_code==200
    for index in (1,2):assert chunk(client,admin_headers,pid,sid,index,data[index*8:(index+1)*8]).status_code==200
    finished=client.post(base+'/finish',headers=admin_headers)
    assert finished.status_code==200,finished.text
    assert finished.json()['file']['file_size']==len(data)
    assert client.get('/api'+finished.json()['file']['download_url'],headers=admin_headers).content==data
    repeated=client.post(base+'/finish',headers=admin_headers)
    assert repeated.status_code==200 and repeated.json()['file']['id']==finished.json()['file']['id']
    with SessionLocal() as db:
        assert db.query(Attachment).filter_by(project_id=pid).count()==1
        assert db.query(DocumentVersion).filter(DocumentVersion.project_document_id.in_(ids)).count()==2
    assert not (config.DATA_DIR/'.upload-sessions'/sid).exists()


def test_bad_complete_hash_never_creates_attachment_or_evidence(client,admin_headers):
    pid=create(client,admin_headers)['id'];did=view(client,admin_headers,pid)['documents'][0]['id']
    before=set(config.UPLOAD_DIR.iterdir())
    data=b'actual private source';session,_=start(client,admin_headers,pid,data,[did],sha256='0'*64)
    assert chunk(client,admin_headers,pid,session['id'],0,data).status_code==200
    assert client.post(f'/api/projects/{pid}/uploads/{session["id"]}/finish',headers=admin_headers).status_code==409
    with SessionLocal() as db:
        assert db.query(Attachment).filter_by(project_id=pid).count()==0
        assert db.query(DocumentVersion).count()==0 and db.get(ProjectDocument,did).status=='pending'
    assert set(config.UPLOAD_DIR.iterdir())==before


def test_chunk_boundaries_hash_and_same_index_content_are_enforced(client,admin_headers,monkeypatch):
    monkeypatch.setattr(config,'UPLOAD_CHUNK_SIZE',8);monkeypatch.setattr(config,'MAX_UPLOAD_BYTES',16)
    pid=create(client,admin_headers)['id'];session,body=start(client,admin_headers,pid,b'abcdefghABCDEFGH')
    sid=session['id'];path=f'/api/projects/{pid}/uploads/{sid}/chunks/0'
    assert chunk(client,admin_headers,pid,sid,2,b'x').status_code==400
    assert chunk(client,admin_headers,pid,sid,0,b'123').status_code==400
    assert chunk(client,admin_headers,pid,sid,0,b'123456789').status_code==413
    assert client.put(path,headers={**admin_headers,'Content-Type':'application/octet-stream','X-Chunk-SHA256':'0'*64},content=b'abcdefgh').status_code==409
    assert chunk(client,admin_headers,pid,sid,0,b'abcdefgh').status_code==200
    assert chunk(client,admin_headers,pid,sid,0,b'ABCDEFGH').status_code==409
    assert client.post(f'/api/projects/{pid}/uploads',headers=admin_headers,json={**body,'size':17,'client_uuid':'too-large-001'}).status_code==413
    assert client.post(f'/api/projects/{pid}/uploads',headers=admin_headers,json={**body,'filename':'different.bin'}).status_code==409


def test_owner_and_current_permission_are_rechecked_before_every_part_and_finish(client,admin_headers,worker_headers):
    p=create(client,admin_headers);pid=p['id']
    assert client.put(f'/api/projects/{pid}',headers=admin_headers,json={'members':[*p['members'],'user-worker-001']}).status_code==200
    session,_=start(client,worker_headers,pid,b'private pending bytes')
    sid=session['id'];base=f'/api/projects/{pid}/uploads/{sid}'
    assert client.get(base,headers=admin_headers).status_code==404
    assert chunk(client,worker_headers,pid,sid,0,b'private pending bytes').status_code==200
    with SessionLocal() as db:
        db.get(User,'user-worker-001').permission_overrides={'worker.deliver':False};db.commit()
    assert client.get(base,headers=worker_headers).status_code==403
    assert chunk(client,worker_headers,pid,sid,0,b'private pending bytes').status_code==403
    assert client.post(base+'/finish',headers=worker_headers).status_code==403
    with SessionLocal() as db:assert db.query(Attachment).filter_by(project_id=pid).count()==0
    assert client.get(f'/api/.upload-sessions/{sid}/part-00000000',headers=admin_headers).status_code==404


def test_finish_failure_rolls_back_published_file_versions_and_session(client,admin_headers,monkeypatch):
    pid=create(client,admin_headers)['id'];did=view(client,admin_headers,pid)['documents'][0]['id']
    before=set(config.UPLOAD_DIR.iterdir())
    session,_=start(client,admin_headers,pid,b'atomic source',[did]);sid=session['id']
    assert chunk(client,admin_headers,pid,sid,0,b'atomic source').status_code==200
    import app.services.project_documents as docs
    original=docs.log_change
    def fail(db,pid,kind,*args,**kwargs):
        if kind=='project_document':raise RuntimeError('simulated evidence audit outage')
        return original(db,pid,kind,*args,**kwargs)
    monkeypatch.setattr(docs,'log_change',fail)
    with pytest.raises(RuntimeError,match='evidence audit outage'):
        client.post(f'/api/projects/{pid}/uploads/{sid}/finish',headers=admin_headers)
    with SessionLocal() as db:
        assert db.query(Attachment).filter_by(project_id=pid).count()==0
        assert db.query(DocumentVersion).count()==0 and db.get(UploadSession,sid).state=='open'
    assert set(config.UPLOAD_DIR.iterdir())==before


def test_finish_uses_explicit_signature_date_without_fabricating_an_actual_time(client,admin_headers):
    pid=create(client,admin_headers)['id'];did=next(row['id'] for row in view(client,admin_headers,pid)['documents'] if row['code']=='4.5')
    session,_=start(client,admin_headers,pid,b'real signed meeting',[did],milestone_dates={'internal_kickoff':'2026-01-02'})
    assert chunk(client,admin_headers,pid,session['id'],0,b'real signed meeting').status_code==200
    finished=client.post(f'/api/projects/{pid}/uploads/{session["id"]}/finish',headers=admin_headers)
    assert finished.status_code==200,finished.text
    events=client.get(f'/api/projects/{pid}/events',headers=admin_headers).json()['events']
    kickoff=next(row for row in events if row['event_key']=='internal_kickoff')
    assert kickoff['actual_date']=='2026-01-02' and kickoff['actual_at'] is None and kickoff['actual_precision']=='date'


def test_session_revocation_during_network_stream_is_rechecked_before_chunk_receipt(client,admin_headers):
    pid=create(client,admin_headers)['id'];data=b'bytes received after session change';session,_=start(client,admin_headers,pid,data)
    def body():
        yield data[:5]
        with SessionLocal() as db:
            actor=db.get(User,'user-admin-001');actor.token_version+=1;db.commit()
        yield data[5:]
    response=client.put(f'/api/projects/{pid}/uploads/{session["id"]}/chunks/0',headers={**admin_headers,
        'Content-Type':'application/octet-stream','X-Chunk-SHA256':hashlib.sha256(data).hexdigest()},content=body())
    assert response.status_code==401,response.text
    from app.models import UploadChunk
    with SessionLocal() as db:assert db.query(UploadChunk).count()==0 and db.query(Attachment).count()==0


def test_concurrent_duplicate_finish_creates_one_original_and_one_evidence_version(client,admin_headers):
    from concurrent.futures import ThreadPoolExecutor
    pid=create(client,admin_headers)['id'];did=view(client,admin_headers,pid)['documents'][0]['id'];data=b'concurrent exact original'
    session,_=start(client,admin_headers,pid,data,[did]);sid=session['id']
    assert chunk(client,admin_headers,pid,sid,0,data).status_code==200
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:client.post(f'/api/projects/{pid}/uploads/{sid}/finish',headers=admin_headers),range(2)))
    assert [response.status_code for response in responses]==[200,200],[response.text for response in responses]
    assert responses[0].json()['file']['id']==responses[1].json()['file']['id']
    with SessionLocal() as db:
        assert db.query(Attachment).filter_by(project_id=pid).count()==1
        assert db.query(DocumentVersion).filter_by(project_document_id=did).count()==1


def test_rolled_back_chunk_cache_retry_creates_one_audited_receipt(client,admin_headers,monkeypatch):
    from app.services import resumable_uploads as uploads
    from app.models import UploadChunk,ChangeLog
    pid=create(client,admin_headers)['id'];data=b'disposable technical cache';session,_=start(client,admin_headers,pid,data);sid=session['id']
    original=uploads.log_change
    def fail(db,pid,kind,identity,action,*args,**kwargs):
        if action=='chunk':raise RuntimeError('chunk audit unavailable')
        return original(db,pid,kind,identity,action,*args,**kwargs)
    monkeypatch.setattr(uploads,'log_change',fail)
    with pytest.raises(RuntimeError,match='chunk audit unavailable'):chunk(client,admin_headers,pid,sid,0,data)
    with SessionLocal() as db:assert db.query(UploadChunk).count()==0
    monkeypatch.setattr(uploads,'log_change',original)
    assert chunk(client,admin_headers,pid,sid,0,data).status_code==200
    with SessionLocal() as db:
        assert db.query(UploadChunk).count()==1
        assert db.query(ChangeLog).filter_by(entity_id=sid,action='chunk').count()==1
