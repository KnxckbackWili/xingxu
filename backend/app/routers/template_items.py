"""Template content: sections, one-row items, custom fields, copying between templates and Excel.

Every write locks the template, re-checks the actor, records the change and recompiles the rows
projects are generated from in the same transaction (services/template_items.py).
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.config import MAX_UPLOAD_SIZE
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import User
from app.services import template_items as content
from app.services.system_permissions import route_permission
from app.services.upload_safety import read_upload_limited

router = APIRouter(prefix="/templates", tags=["模板事项"])


@router.get("/{template_id}/items")
@route_permission("system.templates.read")
def read_items(template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return content.tree(db, template_id)


@router.post("/{template_id}/sections")
@route_permission("system.templates.manage")
def create_section(template_id: str, data: content.SectionIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = content.create_section(db, template_id, data, user.id)
    db.commit()
    return {"id": row.id, **content.tree(db, template_id)}


@router.put("/{template_id}/sections/{section_id}")
@route_permission("system.templates.manage")
def update_section(template_id: str, section_id: str, data: content.SectionUpdate,
                   user: User = Depends(require_admin), db: Session = Depends(get_db)):
    content.update_section(db, template_id, section_id, data, user.id)
    db.commit()
    return content.tree(db, template_id)


@router.delete("/{template_id}/sections/{section_id}")
@route_permission("system.templates.manage")
def delete_section(template_id: str, section_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    content.delete_section(db, template_id, section_id, user.id)
    db.commit()
    return content.tree(db, template_id)


@router.put("/{template_id}/layout")
@route_permission("system.templates.manage")
def set_layout(template_id: str, data: content.LayoutIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    content.set_layout(db, template_id, data, user.id)
    db.commit()
    return content.tree(db, template_id)


@router.post("/{template_id}/items")
@route_permission("system.templates.manage")
def create_item(template_id: str, data: content.ItemIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = content.create_item(db, template_id, data, user.id)
    db.commit()
    return {"id": row.id, **content.tree(db, template_id)}


@router.put("/{template_id}/items/{item_id}")
@route_permission("system.templates.manage")
def update_item(template_id: str, item_id: str, data: content.ItemIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    content.update_item(db, template_id, item_id, data, user.id)
    db.commit()
    return content.tree(db, template_id)


@router.delete("/{template_id}/items/{item_id}")
@route_permission("system.templates.manage")
def delete_item(template_id: str, item_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    content.delete_item(db, template_id, item_id, user.id)
    db.commit()
    return content.tree(db, template_id)


@router.post("/{template_id}/items/copy")
@route_permission("system.templates.manage")
def copy_items(template_id: str, data: content.CopyIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    copied = content.copy_items(db, template_id, data, user.id)
    db.commit()
    return {"copied": [row.id for row in copied], **content.tree(db, template_id)}


@router.put("/{template_id}/fields")
@route_permission("system.templates.manage")
def replace_fields(template_id: str, data: content.FieldsIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    content.replace_fields(db, template_id, data, user.id)
    db.commit()
    return content.tree(db, template_id)


@router.post("/{template_id}/items/{item_id}/files/{file_id}/blank")
@route_permission("system.templates.manage")
async def upload_blank(template_id: str, item_id: str, file_id: str, file: UploadFile = File(...),
                       user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = await read_upload_limited(file, MAX_UPLOAD_SIZE, "空白模板")
    try:
        content.set_blank_file(db, template_id, item_id, file_id, data, file.filename, file.content_type, user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return content.tree(db, template_id)


@router.delete("/{template_id}/items/{item_id}/files/{file_id}/blank")
@route_permission("system.templates.manage")
def clear_blank(template_id: str, item_id: str, file_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    content.clear_blank_file(db, template_id, item_id, file_id, user.id)
    db.commit()
    return content.tree(db, template_id)


@router.get("/{template_id}/items/{item_id}/files/{file_id}/blank")
@route_permission("system.templates.read")
def download_blank(template_id: str, item_id: str, file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.document_requirements import read_asset
    asset = content.blank_file(db, template_id, item_id, file_id)
    return Response(read_asset(asset), media_type=asset.content_type,
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(asset.filename), "Cache-Control": "private, no-store"})


@router.get("/{template_id}/excel")
@route_permission("system.templates.read")
def export_excel(template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = content.export_workbook(db, template_id)
    name = f"{content.template_label(db, template_id)}.xlsx"
    return StreamingResponse(iter([data]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename=\"template.xlsx\"; filename*=UTF-8''{quote(name)}",
                                      "Cache-Control": "private, no-store"})


@router.post("/{template_id}/excel")
@route_permission("system.templates.manage", "system.template_io.manage")
async def import_excel(template_id: str, file: UploadFile = File(...), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = await read_upload_limited(file, MAX_UPLOAD_SIZE, "模板表格")
    result = content.import_workbook(db, template_id, data, user.id)
    db.commit()
    return {"imported": result, **content.tree(db, template_id)}
