"""Bounded private-cache expiry; formal originals only use authorized journals."""
from datetime import timedelta
from uuid import UUID
import shutil,logging,json
from app import config,models
from app.time_utils import utcnow
from app.services.resumable_uploads import discard_parts
from app.services.record_lock import lock_record
from app.services.change_log import log_change
from app.services.storage_cleanup import recover_journals


def maintain_storage(db):
    result=recover_journals(db)
    # Maintenance owns its transaction. Release recovery's project locks before
    # the second sorted pass, avoiding reverse project lock order across workers.
    db.commit()
    now=utcnow();expired=0
    ids=[row.id for row in db.query(models.UploadSession).filter(
        models.UploadSession.state.in_(['open','expired','cancelled','finished'])).order_by(models.UploadSession.project_id,models.UploadSession.id)]
    for identity in ids:
        row=db.get(models.UploadSession,identity);project=db.get(models.Project,row.project_id) if row else None
        if not row or not project:continue
        lock_record(db,project,conflict_detail='上传缓存回收正在等待项目更新')
        db.refresh(row)
        due=row.expires_at<=now
        if row.state=='open' and due and project.deleted_at is None:
            row.state='expired';expired+=1
            log_change(db,row.project_id,'upload_session',row.id,'expire',None,
                '未完成上传已过期，本地队列可保留原文件重新续传',None,{'expires_at':row.expires_at.isoformat()})
        if row.state in ('expired','cancelled','finished') or due:
            # Only disposable chunks; the attachment is never addressed here.
            discard_parts(row)
    root=config.DATA_DIR/'.upload-sessions'
    purged={}
    if root.is_dir() and not root.is_symlink():
        cutoff=(now-timedelta(days=config.UPLOAD_SESSION_TTL_DAYS)).timestamp()
        for directory in root.iterdir():
            try:
                if directory.is_symlink() or not directory.is_dir() or str(UUID(directory.name))!=directory.name:continue
                if db.get(models.UploadSession,directory.name) is None:
                    context=directory/'.context.json';proven=False
                    if context.is_file() and not context.is_symlink() and context.stat().st_size<=512:
                        hint=json.loads(context.read_text());pid=hint.get('project_id')
                        if isinstance(pid,str) and hint.get('session_id')==directory.name and db.get(models.Project,pid) is None:
                            from app.services.storage_purge_evidence import purged_snapshot
                            if pid not in purged:purged[pid]=purged_snapshot(db,pid)
                            snapshot=purged[pid]
                            proven=bool(snapshot and any(row['id']==directory.name and row['project_id']==pid for row in snapshot['records'].get('upload_sessions',[])))
                    if proven or directory.stat().st_mtime<cutoff:shutil.rmtree(directory)
            except (ValueError,OSError,TypeError,AttributeError):logging.getLogger(__name__).warning('Private upload cache reclamation deferred')
    return {**result,'expired':expired}
