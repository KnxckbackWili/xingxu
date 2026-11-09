"""Template-level document definitions and immutable blank forms."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import DocumentTemplateFile, User
from app.services import document_requirements as docs
from app.services.system_permissions import route_permission

router = APIRouter(prefix="/templates", tags=["资料要求模板"])


@router.get("/{template_id}/document-requirements")
@route_permission("system.templates.read")
def list_requirements(template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return docs.list_requirements(db, template_id)


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
