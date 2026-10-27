"""Recoverable project deletions, scoped to current visibility and delete rights."""
from fastapi import APIRouter, Depends, HTTPException
from starlette.background import BackgroundTask
import tempfile
from pathlib import Path
from app.services import backup_crypto as codec
from app import config
from app.models.project_deletion import ProjectPermanentBackup
from app.services import project_permanent_deletion as permanent
from app.services.project_deletion import backup_directory, verified_backup_path
from app.services.rate_limit import rate_limit_export
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.models.project_deletion import ProjectDeletionRecord
from app.services.permissions import authorize_project, project_capabilities, C_DELETE, C_EXPORT
from app.services.scope import visible_projects, ensure_project_visible
from app.services.project_deletion import recycle_item, restore_project

router = APIRouter(prefix="/project-recycle-bin", tags=["项目回收站"])


class RestoreBody(BaseModel):
    version: int = Field(ge=0, strict=True)
    deletion_id: str = Field(min_length=1, max_length=36)


def _record(db, project):
    record = db.query(ProjectDeletionRecord).filter_by(project_id=project.id, restored_at=None).order_by(ProjectDeletionRecord.deleted_at.desc(), ProjectDeletionRecord.id.desc()).first()
    if record is None or project.deleted_at is None or record.deleted_at != project.deleted_at:
        raise HTTPException(404, "可还原的删除记录不存在")
    return record


def _visible(db, project_id, user):
    project = ensure_project_visible(db, project_id, user, include_deleted=True)
    authorize_project(user, project, C_DELETE)
    return project


@router.get("/projects")
@route_permission('project.read', 'project.delete')
def list_recycle_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = []
    for project in visible_projects(db, user, include_deleted=True):
        if project.deleted_at is None or C_DELETE not in project_capabilities(user, project):
            continue
        try:
            record = _record(db, project)
        except HTTPException:
            continue  # Legacy purge-only deletions are not falsely advertised as recoverable.
        result.append(recycle_item(db, project, record, user=user))
    return sorted(result, key=lambda item: (item["deleted_at"], item["id"]), reverse=True)


@router.get("/projects/{project_id}")
@route_permission('project.read', 'project.delete')
def get_recycle_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _visible(db, project_id, user)
    return recycle_item(db, project, _record(db, project), user=user)


@router.post("/projects/{project_id}/restore")
@route_permission('project.read', 'project.delete')
def restore(project_id: str, body: RestoreBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return restore_project(db, project_id, user, version=body.version, deletion_id=body.deletion_id)


@router.get("/projects/{project_id}/backup")
@route_permission('project.read', 'project.delete')
def download(project_id: str, deletion_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _visible(db, project_id, user)
    authorize_project(user, project, C_EXPORT)
    record = _record(db, project)
    if record.id != deletion_id:
        raise HTTPException(404, "删除备份不存在")
    try:
        path = verified_backup_path(record)
    except Exception:
        raise HTTPException(409, "项目备份不存在或校验失败") from None
    if codec.is_encrypted(path):
        return FileResponse(path, media_type='application/octet-stream', filename='项目删除备份.zip.agvenc', headers={'Cache-Control': 'no-store'})
    # Do not publish historical plaintext; retain its original bytes unchanged.
    staging = tempfile.TemporaryDirectory(prefix='.project-download-', dir=backup_directory())
    encrypted = Path(staging.name) / 'project.zip.agvenc'
    try:
        codec.encrypt_file(path, encrypted, codec.get_passphrase(config.DATA_DIR))
    except Exception:
        staging.cleanup()
        raise HTTPException(409, '历史备份加密失败，请管理员配置备份口令') from None
    return FileResponse(encrypted, media_type='application/octet-stream', filename='项目删除备份.zip.agvenc',
                        headers={'Cache-Control': 'no-store'}, background=BackgroundTask(staging.cleanup))


class PermanentBody(RestoreBody):
    backup_id: str = Field(min_length=36, max_length=36)
    confirm_name: str = Field(min_length=1, max_length=200)


@router.post('/projects/{project_id}/permanent-backup')
@route_permission('project.read', 'project.delete', 'project.export', 'system.projects.purge')
def prepare_permanent_backup(project_id: str, body: RestoreBody, user: User = Depends(rate_limit_export()), db: Session = Depends(get_db)):
    return permanent.prepare(db, project_id, user, version=body.version, deletion_id=body.deletion_id)


@router.delete('/projects/{project_id}/permanent')
@route_permission('project.read', 'project.delete', 'project.export', 'system.projects.purge')
def permanent_delete(project_id: str, body: PermanentBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return permanent.permanently_delete(db, project_id, user, version=body.version, deletion_id=body.deletion_id,
                                       backup_id=body.backup_id, confirm_name=body.confirm_name)


@router.get('/backups/{backup_id}')
@route_permission('project.read', 'project.delete', 'project.export', 'system.projects.purge')
def download_permanent_backup(backup_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    permanent.require_admin(user)
    receipt = db.get(ProjectPermanentBackup, backup_id)
    if not receipt:
        raise HTTPException(404, '加密备份不存在')
    try:
        path = verified_backup_path(receipt)
        if not codec.is_encrypted(path): raise OSError('not encrypted')
    except Exception:
        raise HTTPException(409, '加密备份不存在或校验失败') from None
    return FileResponse(path, filename='项目永久删除备份.zip.agvenc', media_type='application/octet-stream', headers={'Cache-Control': 'no-store'})


@router.get('/permanent-backups')
@route_permission('project.read', 'project.delete', 'project.export', 'system.projects.purge')
def list_permanent_backups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    permanent.require_admin(user)
    rows = db.query(ProjectPermanentBackup).order_by(ProjectPermanentBackup.prepared_at.desc()).all()
    return [permanent.receipt_payload(row) for row in rows]
