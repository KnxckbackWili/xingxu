"""Old-period byte removal remains a complete, verifiable business fact."""
import hashlib,json
from datetime import datetime,date,timedelta
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app import config,models
from app.db import SessionLocal
from app.services import storage_cleanup as cleanup
from app.services.file_retention import retained_submission,manifest_removal
from app.services.project_documents import validate_file
from .test_project_documents import create,view


def weekly(client,headers,count=10):
    pid=create(client,headers)['id'];ids=[]
    with SessionLocal() as db:
        # Fixtures preserve the real old submission and its actual file, rather
        # than marking task.done or synthesizing a filename as evidence.
        for index in range(count):
            did=str(uuid4());aid=str(uuid4());stored=uuid4().hex;data=f'real weekly original {index}'.encode()
            (config.UPLOAD_DIR/stored).write_bytes(data)
            document=models.ProjectDocument(id=did,project_id=pid,instance_key=f'fixture-series:project:2025-W{index+1:02}',
                stage_key='5',code='5.weekly',name='现场周报',required=True,scope='project',timing_type='weekly',timing_weekday=6,
                period_key=f'2025-W{index+1:02}',status='submitted',submitted_by='user-admin-001',submitted_at=datetime(2025,1,6)+timedelta(weeks=index))
            asset=models.Attachment(id=aid,project_id=pid,entity_type='project',entity_id=pid,stored_name=stored,filename=f'week-{index+1}.txt',
                file_size=len(data),sha256=hashlib.sha256(data).hexdigest(),uploaded_by='user-admin-001')
            db.add_all([document,asset]);db.flush()
            version=models.DocumentVersion(project_document_id=did,attachment_id=aid,uploaded_by='user-admin-001',uploaded_at=document.submitted_at)
            db.add(version);ids.append((did,aid,stored))
        db.commit()
    return pid,ids


def preview(client,headers,pid,keep=8):
    response=client.post(f'/api/projects/{pid}/storage/cleanup-preview',headers=headers,json={'keep_periods':keep})
    assert response.status_code==200,response.text
    return response.json()


def confirm(client,headers,pid,p):
    return client.post(f'/api/projects/{pid}/storage/cleanup-confirm',headers=headers,json={
        'keep_periods':p['keep_periods'],'fingerprint':p['fingerprint'],'reason':'按公司最近8期策略清理旧原件'})


def test_preview_is_readonly_cleanup_old_unique_versions_preserves_gate_and_history(client,admin_headers):
    pid,rows=weekly(client,admin_headers)
    with SessionLocal() as db:before=db.query(models.ChangeLog).count()
    p=preview(client,admin_headers,pid)
    assert {row['attachment_id'] for row in p['candidates']}=={row[1] for row in rows[:2]}
    assert 'stored_name' not in p['candidates'][0]
    with SessionLocal() as db:assert db.query(models.ChangeLog).count()==before
    result=confirm(client,admin_headers,pid,p)
    assert result.status_code==200,result.text
    assert result.json()['removed_files']==2 and result.json()['released_bytes']==p['candidate_bytes']
    assert not (config.UPLOAD_DIR/rows[0][2]).exists() and (config.UPLOAD_DIR/rows[-1][2]).is_file()
    state=view(client,admin_headers,pid);old=next(row for row in state['documents'] if row['id']==rows[0][0])
    assert old['status']=='submitted' and old['versions'][0]['storage_state']=='removed_by_policy'
    assert old['versions'][0]['download_url']==''
    response=client.get('/api/files/'+rows[0][1]+'/download',headers=admin_headers)
    assert response.status_code==410 and '清理' in response.text
    with SessionLocal() as db:
        d=db.get(models.ProjectDocument,rows[0][0]);a=db.get(models.Attachment,rows[0][1]);v=db.query(models.DocumentVersion).filter_by(project_document_id=d.id).one()
        assert retained_submission(db,db.get(models.Project,pid),d,v,a)
        from app.services.lifecycle_gates import _pending_required_documents
        assert '5.weekly 现场周报' not in _pending_required_documents(db,pid)
        # Every ordinary missing file still blocks. Current/latest periods can
        # never borrow an old-period tombstone to prove present bytes.
        latest=db.get(models.Attachment,rows[-1][1]);(config.UPLOAD_DIR/latest.stored_name).unlink()
        with pytest.raises(HTTPException):validate_file(latest)
        assert not retained_submission(db,db.get(models.Project,pid),db.get(models.ProjectDocument,rows[-1][0]),v,latest)
        assert '5.weekly 现场周报' in _pending_required_documents(db,pid)
        assert db.query(models.DocumentVersion).count()==10 and db.query(models.FileRemovalRecord).count()==2


@pytest.mark.parametrize('change',['project','event','file','reference'])
def test_confirm_fails_409_after_any_relevant_preview_change_without_partial_cleanup(client,admin_headers,change):
    pid,rows=weekly(client,admin_headers);p=preview(client,admin_headers,pid)
    with SessionLocal() as db:
        if change=='project':db.get(models.Project,pid).name='Changed after preview'
        elif change=='event':
            db.add(models.ProjectEvent(project_id=pid,event_key='acceptance',actual_date=date(2025,1,8),actual_source={'kind':'document_signature'}))
        elif change=='file':(config.UPLOAD_DIR/rows[0][2]).write_bytes(b'changed in place')
        else:
            document=db.query(models.ProjectDocument).filter_by(project_id=pid,timing_type='on_demand').first()
            db.add(models.DocumentVersion(project_document_id=document.id,attachment_id=rows[0][1],uploaded_by='user-admin-001'))
        db.commit()
    assert confirm(client,admin_headers,pid,p).status_code==409
    with SessionLocal() as db:assert db.query(models.FileRemovalRecord).count()==0
    assert all((config.UPLOAD_DIR/row[2]).is_file() for row in rows)


def test_date_precision_protects_week_and_neighbors_and_backfill_warns_truthfully(client,admin_headers):
    pid,rows=weekly(client,admin_headers)
    p=preview(client,admin_headers,pid);assert confirm(client,admin_headers,pid,p).status_code==200
    with SessionLocal() as db:
        db.add(models.ProjectEvent(project_id=pid,event_key='acceptance',actual_date=date(2025,1,8),actual_source={'kind':'document_signature','time_basis':'签单业务日期'}));db.commit()
    warnings=view(client,admin_headers,pid)['storage_warnings']
    assert warnings and '原字节不可再下载' in warnings[0]
    protected=preview(client,admin_headers,pid)['protected'];assert any('日期精度' in row['reason'] or '当日' in row['reason'] for row in protected)
    with SessionLocal() as db:
        db.query(models.ProjectEvent).filter_by(project_id=pid).delete()
        db.add(models.ProjectEvent(project_id=pid,event_key='handover',actual_at=datetime(2025,2,1),actual_source={'kind':'legacy_status_transition'}));db.commit()
    assert not preview(client,admin_headers,pid,1)['candidates']


def test_other_real_file_refs_are_protected_and_rollback_restores_all_originals(client,admin_headers,monkeypatch):
    pid,rows=weekly(client,admin_headers)
    with SessionLocal() as db:
        other=db.query(models.ProjectDocument).filter_by(project_id=pid,timing_type='on_demand').first()
        db.add(models.DocumentVersion(project_document_id=other.id,attachment_id=rows[0][1],uploaded_by='user-admin-001'));db.commit()
    p=preview(client,admin_headers,pid)
    assert {row['attachment_id'] for row in p['candidates']}=={rows[1][1]}
    original=cleanup.log_change
    def fail(db,pid,kind,*args,**kwargs):
        if kind=='file_cleanup_receipt':raise RuntimeError('audit not available')
        return original(db,pid,kind,*args,**kwargs)
    monkeypatch.setattr(cleanup,'log_change',fail)
    with pytest.raises(RuntimeError,match='audit not available'):confirm(client,admin_headers,pid,p)
    assert all((config.UPLOAD_DIR/row[2]).is_file() for row in rows)
    with SessionLocal() as db:assert db.query(models.FileRemovalRecord).count()==0
    assert not list((config.DATA_DIR/'.storage-trash').glob('*.bin'))


def test_cleanup_tombstones_allow_encrypted_backup_restore_and_reject_tamper(client,admin_headers):
    from app.services.project_deletion import project_backup_snapshot,create_project_backup,backup_zip
    pid,rows=weekly(client,admin_headers);p=preview(client,admin_headers,pid);assert confirm(client,admin_headers,pid,p).status_code==200
    with SessionLocal() as db:
        project=db.get(models.Project,pid);snapshot,path,_,_=create_project_backup(db,project,str(uuid4()))
        manifest=snapshot['binary_files']['manifest'];removed=[row for row in manifest if row.get('intentionally_removed')]
        assert len(removed)==2 and all(manifest_removal(snapshot,row) for row in removed)
        with backup_zip(path) as archive:
            assert all('path' not in row for row in removed)
            assert all(archive.read(row['path'])==f'real weekly original {rows.index(next(v for v in rows if v[1]==row["references"][0]["id"]))}'.encode() for row in manifest if not row.get('intentionally_removed'))
        snapshot['records']['file_cleanup_receipts'][0]['policy']['kind']='forged'
        assert not manifest_removal(snapshot,removed[0])
        asset=db.get(models.Attachment,rows[-1][1]);(config.UPLOAD_DIR/asset.stored_name).unlink()
        with pytest.raises(OSError,match='missing project file'):project_backup_snapshot(db,project)


def test_storage_usage_excludes_removed_bytes_and_expired_cache_restarts_original_intent(client,admin_headers):
    from .test_resumable_uploads import start,chunk
    from app.services.storage_maintenance import maintain_storage
    pid,rows=weekly(client,admin_headers);p=preview(client,admin_headers,pid);assert confirm(client,admin_headers,pid,p).status_code==200
    usage=client.get(f'/api/projects/{pid}/storage',headers=admin_headers)
    assert usage.status_code==200,usage.text
    assert usage.json()['file_count']==8 and usage.json()['removed_file_count']==2
    session,body=start(client,admin_headers,pid,b'cache only')
    assert chunk(client,admin_headers,pid,session['id'],0,b'cache only').status_code==200
    with SessionLocal() as db:
        db.get(models.UploadSession,session['id']).expires_at=datetime(2020,1,1);db.commit()
        assert maintain_storage(db)['expired']==1;db.commit()
    assert not (config.DATA_DIR/'.upload-sessions'/session['id']).exists()
    restarted=client.post(f'/api/projects/{pid}/uploads',headers=admin_headers,json=body)
    assert restarted.status_code==200 and restarted.json()['id']==session['id'] and restarted.json()['received']==[]


def test_authorized_removed_facts_survive_recycle_restore_and_verified_permanent_purge(client,admin_headers):
    from .test_project_recycle_bin import _delete
    from .test_retention_unification import prepare,purge
    from .test_resumable_uploads import start,chunk
    pid,rows=weekly(client,admin_headers);p=preview(client,admin_headers,pid);assert confirm(client,admin_headers,pid,p).status_code==200
    # Nonempty upload/chunk records are also project audit facts and must be in
    # the complete snapshot before #85 can remove the project graph.
    session,_=start(client,admin_headers,pid,b'unfinished private data')
    assert chunk(client,admin_headers,pid,session['id'],0,b'unfinished private data').status_code==200
    # Simulate a committed cleanup whose post-commit unlink was interrupted.
    with SessionLocal() as db:
        removal=db.query(models.FileRemovalRecord).filter_by(attachment_id=rows[0][1]).one()
        identity=removal.id
        pending={'stored_name':removal.stored_name,'sha256':removal.sha256,'size':removal.file_size,'project_id':pid,'attachment_id':rows[0][1]}
    directory=cleanup.trash_directory();(directory/(identity+'.json')).write_text(json.dumps(pending))
    (directory/(identity+'.bin')).write_bytes(b'real weekly original 0')
    project=client.get('/api/projects/'+pid,headers=admin_headers).json()
    assert _delete(client,admin_headers,project).status_code==200
    row=client.get('/api/project-recycle-bin/projects/'+pid,headers=admin_headers).json()
    restored=client.post(f'/api/project-recycle-bin/projects/{pid}/restore',headers=admin_headers,json={'version':row['version'],'deletion_id':row['deletion_id']})
    assert restored.status_code==200,restored.text
    assert next(row for row in view(client,admin_headers,pid)['documents'] if row['id']==rows[0][0])['versions'][0]['storage_state']=='removed_by_policy'
    project=client.get('/api/projects/'+pid,headers=admin_headers).json()
    assert _delete(client,admin_headers,project).status_code==200
    row=client.get('/api/project-recycle-bin/projects/'+pid,headers=admin_headers).json()
    prepared=prepare(client,admin_headers,row);assert prepared.status_code==200,prepared.text
    response=purge(client,admin_headers,row,prepared.json());assert response.status_code==200,response.text
    with SessionLocal() as db:
        assert db.get(models.Project,pid) is None
        for model in (models.UploadSession,models.UploadChunk,models.FileCleanupReceipt,models.FileRemovalRecord):
            assert db.query(model).filter_by(project_id=pid).count()==0
        from app.services.storage_maintenance import maintain_storage
        assert maintain_storage(db)['reclaimed']>=1;db.commit()
    assert not (directory/(identity+'.bin')).exists() and not (config.UPLOAD_DIR/rows[0][2]).exists()
    assert not (config.DATA_DIR/'.upload-sessions'/session['id']).exists()


def test_system_backup_uses_consistent_removal_inventory_and_fails_for_ordinary_missing(client,admin_headers,tmp_path):
    import sqlite3
    from app.db import engine
    from app.services import backup_crypto as codec
    pid,rows=weekly(client,admin_headers);p=preview(client,admin_headers,pid);assert confirm(client,admin_headers,pid,p).status_code==200
    if engine.dialect.name=='sqlite' and Path(engine.url.database).resolve()!=(config.DATA_DIR/'agvpm.db').resolve():
        source=sqlite3.connect(engine.url.database);target=sqlite3.connect(config.DATA_DIR/'agvpm.db')
        source.backup(target);source.close();target.close()
    archive=tmp_path/'system.agvenc'
    codec.create_archive(config.DATA_DIR,archive,config.DATABASE_URL,'test-only-backup-password-2026')
    manifest=codec.validate_archive(archive,'test-only-backup-password-2026')
    assert manifest['storage']['policy_removed_files']==2 and '历史字节不在包内' in manifest['storage']['byte_recovery']
    (config.UPLOAD_DIR/rows[-1][2]).unlink()
    with pytest.raises(codec.BackupError,match='普通原件缺失'):
        codec.create_archive(config.DATA_DIR,tmp_path/'must-not-publish.agvenc',config.DATABASE_URL,'test-only-backup-password-2026')
    assert not (tmp_path/'must-not-publish.agvenc').exists()


def test_cleanup_crash_journal_restores_uncommitted_original_and_keeps_truthful_package(client,admin_headers,tmp_path):
    from app.services.import_export import project_package_stream
    from zipfile import ZipFile
    pid,rows=weekly(client,admin_headers);did,aid,stored=rows[0]
    identity=str(uuid4());directory=cleanup.trash_directory();path=config.UPLOAD_DIR/stored;data=path.read_bytes()
    metadata={'stored_name':stored,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'project_id':pid,'attachment_id':aid}
    journal=directory/(identity+'.json');journal.write_text(json.dumps(metadata));path.replace(directory/(identity+'.bin'))
    with SessionLocal() as db:
        assert cleanup.recover_journals(db)['restored']==1;db.commit()
    assert path.read_bytes()==data and not journal.exists()
    p=preview(client,admin_headers,pid);assert confirm(client,admin_headers,pid,p).status_code==200
    with SessionLocal() as db:
        with project_package_stream(db,pid,db.get(models.User,'user-admin-001')) as handle,ZipFile(handle) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            removed=[row for row in manifest['files'] if row.get('storage_state')=='removed_by_policy']
            assert len(removed)==2 and all(row['archive_path'] is None and not row.get('missing') for row in removed)
            assert manifest['missing_count']==0


def test_private_preview_audits_only_actual_view_and_does_not_invalidate_fingerprint(client,admin_headers):
    from .test_confidential_documents_t26 import policy
    pid,rows=weekly(client,admin_headers)
    file=next(row for row in client.get(f'/api/projects/{pid}/documents/files',headers=admin_headers).json() if row['id']==rows[0][1])
    changed=policy(client,admin_headers,pid,'file',file,[]);assert changed.status_code==200,changed.text
    with SessionLocal() as db:before=db.query(models.ChangeLog).filter_by(project_id=pid,action='confidential_view').count()
    first=preview(client,admin_headers,pid);second=preview(client,admin_headers,pid)
    assert first['fingerprint']==second['fingerprint'] and (config.UPLOAD_DIR/rows[0][2]).is_file()
    with SessionLocal() as db:
        assert db.query(models.ChangeLog).filter_by(project_id=pid,action='confidential_view').count()==before+2
        assert db.query(models.FileRemovalRecord).count()==0
    assert confirm(client,admin_headers,pid,second).status_code==200
