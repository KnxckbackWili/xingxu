"""Template-level document definitions and immutable blank forms."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import MAX_UPLOAD_SIZE
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import DocumentTemplateFile, User
from app.services import document_requirements as docs
from app.services.change_log import log_change
from app.services.system_permissions import route_permission
from app.services.upload_safety import read_upload_limited

router = APIRouter(prefix="/templates", tags=["资料要求模板"])


@router.get("/{template_id}/document-requirements")
@route_permission("system.templates.read")
def list_requirements(template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return docs.list_requirements(db, template_id)


@router.post("/{template_id}/document-requirements")
@route_permission("system.templates.manage")
def create_requirement(template_id: str, body: docs.RequirementInput,
                       user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        row = docs.save_requirement(db, template_id, body, user.id)
        db.commit()
        return docs.requirement_dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "资料编号已被其他操作使用，请刷新后重试") from None


@router.put("/{template_id}/document-requirements/{requirement_id}")
@route_permission("system.templates.manage")
def update_requirement(template_id: str, requirement_id: str, body: docs.RequirementInput,
                       user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        row = docs.save_requirement(db, template_id, body, user.id, requirement_id)
        db.commit()
        return docs.requirement_dict(row)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "资料编号已被其他操作使用，请刷新后重试") from None


@router.delete("/{template_id}/document-requirements/{requirement_id}")
@route_permission("system.templates.manage")
def delete_requirement(template_id: str, requirement_id: str,
                       user: User = Depends(require_admin), db: Session = Depends(get_db)):
    docs.delete_requirement(db, template_id, requirement_id, user.id)
    db.commit()
    return {"message": "资料要求已删除，既有项目和历史模板文件保留"}


@router.post("/{template_id}/document-requirements/{requirement_id}/blank-file")
@route_permission("system.templates.manage")
async def upload_blank(template_id: str, requirement_id: str, file: UploadFile = File(...),
                       user: User = Depends(require_admin), db: Session = Depends(get_db)):
    docs.lock_templates(db, template_id)
    docs.recheck_authority(db, user.id)
    row = docs.owned_requirement(db, template_id, requirement_id)
    if row.is_group:
        raise HTTPException(400, "分组不能上传空白模板，请选择具体资料要求")
    data = await read_upload_limited(file, MAX_UPLOAD_SIZE, "空白模板")
    try:
        asset = docs.create_file(db, data, file.filename, file.content_type, user.id)
        before = row.blank_file_id
        row.blank_file_id = asset.id
        docs.draft(db, template_id)
        log_change(db, None, "document_requirement", row.id, "blank_file", user.id,
                   f"上传空白模板：{row.code} {asset.filename}", {"blank_file_id": before}, {"blank_file_id": asset.id, "sha256": asset.sha256})
        db.commit()
        return docs.file_dict(asset)
    except Exception:
        db.rollback()
        raise


@router.delete("/{template_id}/document-requirements/{requirement_id}/blank-file")
@route_permission("system.templates.manage")
def detach_blank(template_id: str, requirement_id: str,
                 user: User = Depends(require_admin), db: Session = Depends(get_db)):
    docs.lock_templates(db, template_id)
    docs.recheck_authority(db, user.id)
    row = docs.owned_requirement(db, template_id, requirement_id)
    before = row.blank_file_id
    row.blank_file_id = None
    docs.draft(db, template_id)
    log_change(db, None, "document_requirement", row.id, "blank_file", user.id,
               f"移除空白模板引用：{row.code}", {"blank_file_id": before}, {"blank_file_id": None})
    db.commit()
    return {"message": "已移除当前引用，历史版本文件保留"}


@router.get("/{template_id}/document-requirements/{requirement_id}/blank-file")
@route_permission("system.templates.read")
def download_blank(template_id: str, requirement_id: str,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = docs.owned_requirement(db, template_id, requirement_id)
    asset = db.get(DocumentTemplateFile, row.blank_file_id) if row.blank_file_id else None
    if asset is None:
        raise HTTPException(404, "尚未上传空白模板")
    return Response(docs.read_asset(asset), media_type=asset.content_type,
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(asset.filename), "Cache-Control": "private, no-store"})
