"""Attachment routes: upload, list, download, delete.

附件可挂载到 project / task / issue（entity_type + entity_id），
上传权限：项目成员或 PM/admin（现场人员可传问题照片、交付文件）。
"""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.config import UPLOAD_DIR
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Attachment, Task
from app.services.scope import ensure_project_visible
from app.services.change_log import log_change

router = APIRouter(tags=["附件"])

@router.get("/files/{attachment_id}/download")
@route_permission('project.read')
def download_attachment(attachment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.get(Attachment, attachment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    # 按附件所属项目做可见性校验（防止拿 id 任意下载他人项目文件）
    from app.services.project_documents import can_read_file, validate_file, audit_access
    project = ensure_project_visible(db, a.project_id, user)
    if not can_read_file(user, project, a):
        raise HTTPException(403, "没有该保密文件的下载权限")
    path = validate_file(a)
    audit_access(db, project, user, files=[a], action='confidential_dl')
    db.commit()
    return FileResponse(
        path=str(path),
        filename=a.filename,
        media_type=a.content_type or "application/octet-stream",
        headers={"Cache-Control":"private, no-store"},
    )


@router.delete("/files/{attachment_id}")
@route_permission('project.update')
def delete_attachment(attachment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.permissions import authorize_project, C_UPDATE
    a = db.get(Attachment, attachment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    project = ensure_project_visible(db, a.project_id, user)
    from app.services.record_lock import lock_writable_project
    lock_writable_project(db, project, user)
    db.refresh(user)
    if not user.is_active:raise HTTPException(401,"账号已停用，请重新登录")
    project=ensure_project_visible(db,project.id,user)
    authorize_project(user, project, C_UPDATE)
    # Re-read after the project lock: another deletion may have finished while
    # this request waited. Do not unlink a file or log a second deletion then.
    a = db.query(Attachment).filter_by(id=attachment_id).populate_existing().first()
    if a is None:
        raise HTTPException(404, "附件不存在")
    from app.services.project_documents import can_read_file
    if not can_read_file(user,project,a):raise HTTPException(403,"无权删除该保密文件")
    from app.models import AcceptanceRecord, ArchiveChecklist, VehicleLifecycleEvent, DocumentVersion
    if db.query(DocumentVersion.id).filter_by(attachment_id=a.id).first():
        raise HTTPException(400, "附件仍被资料版本引用，不能删除历史证据")
    for task in db.query(Task).filter_by(project_id=project.id).all():
        if any(isinstance(item, dict) and item.get("attachment_id") == a.id for item in task.deliverables or []):
            raise HTTPException(400, f"附件仍被任务「{task.name}」的交付物引用，请先撤回或更换交付附件")
    if db.query(AcceptanceRecord.id).filter_by(attachment_id=a.id).first():
        raise HTTPException(400, "附件是已保存验收记录的证据，不能直接删除")
    if db.query(ArchiveChecklist.id).filter_by(attachment_id=a.id).first():
        raise HTTPException(400, "附件仍被归档清单引用，请先解除或更换清单附件")
    if db.query(VehicleLifecycleEvent.id).filter_by(attachment_id=a.id).first():
        raise HTTPException(400, "附件仍被车辆事件引用，请先解除或更换事件附件")

    from app.models import TemplateDoc, DocumentTemplateFile
    shared_file = (db.query(Attachment.id).filter(
        Attachment.stored_name == a.stored_name, Attachment.id != a.id).first() is not None
        or db.query(TemplateDoc.id).filter_by(stored_name=a.stored_name).first() is not None
        or db.query(DocumentTemplateFile.id).filter_by(stored_name=a.stored_name).first() is not None)
    if not shared_file:
        shared_file = any(isinstance(ref, dict) and ref.get("stored_name") == a.stored_name
                          for (refs,) in db.query(Task.reference_docs).all() for ref in refs or [])
    from app.services.project_retention import is_retained_file
    shared_file = shared_file or is_retained_file(db, a.stored_name)
    stored=a.stored_name
    path=UPLOAD_DIR/stored
    if not stored or Path(stored).name!=stored or "\\" in stored or path.is_symlink() or path.resolve().parent!=UPLOAD_DIR.resolve():
        raise HTTPException(409,"附件存储路径无效，未删除文件")
    filename, project_id = a.filename, a.project_id
    db.delete(a)
    db.flush()
    log_change(db, project_id, "attachment", attachment_id, "delete", user.id, f"删除附件：{filename}")
    db.commit()
    # Never destroy bytes before the DB deletion and its audit have committed.
    # Failed cleanup is an orphan for the cleanup SOP, not a failed deletion or
    # a reason to report 500 after the transaction has already succeeded.
    if not shared_file:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.getLogger(__name__).warning("Attachment file cleanup deferred: %s", path.name, exc_info=True)
    return {"message": "附件已删除"}
