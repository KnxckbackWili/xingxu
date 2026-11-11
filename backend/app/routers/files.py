"""Files under a document line, an issue, or the project's other files."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models, records
from app.db import get_db
from app.deps import get_current_user
from app.routers.projects import file_dict
from app.services import files as storage
from app.services.change_log import log_change
from app.time_utils import utcnow

router = APIRouter(tags=["文件"])
OWNERS = {"document": models.Document, "issue": models.Issue}


def _owner(db: Session, project_id: str, owner_kind: str, owner_id: str):
    if owner_kind == "other":
        return None
    model = OWNERS.get(owner_kind)
    if model is None:
        raise HTTPException(400, "文件归属不正确")
    row = db.query(model).filter_by(id=owner_id, project_id=project_id, deleted_at=None).first()
    if row is None:
        raise HTTPException(404, "要挂文件的那条记录不存在或已删除")
    return row


@router.post("/projects/{project_id}/files")
async def upload(project_id: str, file: UploadFile = File(...), owner_kind: str = Form("other"),
                 owner_id: str = Form(""), id: str = Form(""),
                 user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    records.load_scope(db, "project", project_id)
    owner = _owner(db, project_id, owner_kind, owner_id)
    if id:
        if not records._UUID.match(id):
            raise HTTPException(400, "文件编号格式不正确")
        existing = db.get(models.File, id)
        if existing is not None:
            if existing.project_id != project_id or existing.deleted_at is not None:
                raise HTTPException(409, "文件编号已被占用")
            return file_dict(existing)  # the same upload sent twice
    file_id = id or models.gen_uuid()
    name = storage.safe_name(file.filename)
    path, size, digest = await storage.store(file, project_id, file_id)
    try:
        row = models.File(id=file_id, project_id=project_id, owner_kind=owner_kind, owner_id=owner.id if owner else None,
                          filename=name, size=size, mime=storage.mime_of(name), sha256=digest, storage_path=path,
                          created_by=user.id)
        db.add(row)
        log_change(db, project_id, "files", file_id, "create", user, "上传文件", new_value={"size": size}, row_label=name)
        records.bump(db, models.Project, project_id)
        db.commit()
    except BaseException:
        storage.discard(path)
        raise
    return file_dict(row)


def _file(db: Session, file_id: str, *, deleted: bool = False) -> models.File:
    row = db.get(models.File, file_id)
    project = db.get(models.Project, row.project_id) if row else None
    if row is None or project is None or project.deleted_at is not None or (row.deleted_at is not None) != deleted:
        raise HTTPException(404, "文件不存在或已删除")
    return row


@router.get("/files/{file_id}")
def download(file_id: str, download: bool = False, _: models.User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    row = _file(db, file_id)
    path = storage.absolute(row.storage_path)
    if not path.is_file():
        raise HTTPException(404, "文件内容已不在服务器上")
    inline = row.mime in storage.INLINE_TYPES and not download
    return FileResponse(path, media_type=row.mime if inline else "application/octet-stream", filename=row.filename,
                        content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.delete("/files/{file_id}")
def delete_file(file_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(models.File, file_id)
    if row is None or row.deleted_at is not None:
        return {"id": file_id, "deleted": True}
    records.load_scope(db, "project", row.project_id)
    row.deleted_at = utcnow()
    log_change(db, row.project_id, "files", row.id, "delete", user, "删除文件", row_label=row.filename)
    records.bump(db, models.Project, row.project_id)
    db.commit()
    return {"id": file_id, "deleted": True}


@router.post("/files/{file_id}/restore")
def restore_file(file_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(models.File, file_id)
    if row is None:
        raise HTTPException(404, "文件已被彻底清除，无法恢复")
    records.load_scope(db, "project", row.project_id)
    if row.deleted_at is not None:
        if row.owner_kind != "other":
            _owner(db, row.project_id, row.owner_kind, row.owner_id)
        row.deleted_at = None
        log_change(db, row.project_id, "files", row.id, "restore", user, "恢复文件", row_label=row.filename)
        records.bump(db, models.Project, row.project_id)
        db.commit()
    return file_dict(row)
