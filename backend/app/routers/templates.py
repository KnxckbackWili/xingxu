"""Templates (four lists copied into a new project) and the vehicle type library."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, records
from app.db import get_db
from app.deps import get_current_user
from app.records import KINDS, TEMPLATE_FIELDS, iso
from app.services.change_log import log_change
from app.time_utils import utcnow

router = APIRouter(tags=["模板与车型"])
ROWS = KINDS["rows"]


def template_dict(template: models.Template, counts=None) -> dict:
    data = {"id": template.id, "name": template.name, "note": template.note, "rev": template.rev,
            "updated_at": iso(template.updated_at)}
    if counts is not None:
        data["counts"] = {kind: counts.get((template.id, kind), 0) for kind in ("work", "document", "step", "item")}
    return data


def template_rows(db: Session, template_id: str):
    return (db.query(models.TemplateRow).filter_by(template_id=template_id, deleted_at=None)
            .order_by(models.TemplateRow.sort_order, models.TemplateRow.created_at).all())


@router.get("/templates")
def list_templates(_: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = {(template_id, kind): count for template_id, kind, count in
              db.query(models.TemplateRow.template_id, models.TemplateRow.kind, func.count())
              .filter(models.TemplateRow.deleted_at.is_(None)).group_by(models.TemplateRow.template_id, models.TemplateRow.kind)}
    return [template_dict(template, counts) for template in
            db.query(models.Template).filter_by(deleted_at=None).order_by(models.Template.created_at)]


@router.post("/templates")
def create_template(body: dict = Body(...), user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    template_id = body.get("id")
    if template_id is not None:
        if not isinstance(template_id, str) or not records._UUID.match(template_id):
            raise HTTPException(400, "模板编号格式不正确")
        existing = db.get(models.Template, template_id)
        if existing is not None:
            return template_dict(existing)
    template = models.Template(id=template_id or models.gen_uuid(), created_by=user.id,
                               name=records.clean(TEMPLATE_FIELDS["name"], body.get("name")),
                               note=records.clean(TEMPLATE_FIELDS["note"], body.get("note")))
    db.add(template)
    log_change(db, None, "template", template.id, "create", user, "新建模板", row_label=template.name)
    db.commit()
    return template_dict(template)


@router.get("/templates/{template_id}")
def get_template(template_id: str, request: Request, _: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    template = records.load_scope(db, "template", template_id)
    etag = f'"{template.id}-{template.rev}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse({"template": template_dict(template),
                         "rows": [records.row_dict(ROWS, row) for row in template_rows(db, template.id)],
                         "people": {user.id: user.display_name for user in db.query(models.User)}},
                        headers={"ETag": etag})


@router.patch("/templates/{template_id}")
def update_template(template_id: str, changes: dict = Body(...), user: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    template = db.query(models.Template).filter_by(id=template_id, deleted_at=None).with_for_update().first()
    if template is None:
        raise HTTPException(404, "模板不存在或已删除")
    try:
        changed = records.apply_changes(db, user, template, TEMPLATE_FIELDS, changes, scope_id=template.id,
                                        kind_key="template", label="模板", row_label=template.name, project_id=None)
    except records.Conflict as conflict:
        return JSONResponse(status_code=409, content={"detail": "这一格刚被别人改过", "conflicts": conflict.conflicts,
                                                      "row": template_dict(template)})
    if changed:
        records.bump(db, models.Template, template.id)
    db.commit()
    db.refresh(template)
    return template_dict(template)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    template = db.query(models.Template).filter_by(id=template_id, deleted_at=None).first()
    if template is not None:
        template.deleted_at = utcnow()
        log_change(db, None, "template", template.id, "delete", user, "删除模板", row_label=template.name)
        db.commit()
    return {"id": template_id, "deleted": True}


@router.post("/templates/{template_id}/restore")
def restore_template(template_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    template = db.get(models.Template, template_id)
    if template is None:
        raise HTTPException(404, "模板已被彻底清除，无法恢复")
    if template.deleted_at is not None:
        template.deleted_at = None
        log_change(db, None, "template", template.id, "restore", user, "恢复模板", row_label=template.name)
        db.commit()
    return template_dict(template)


@router.post("/templates/{template_id}/copy")
def copy_template(template_id: str, body: dict = Body(default={}), user: models.User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    source = records.load_scope(db, "template", template_id)
    name = records.clean(TEMPLATE_FIELDS["name"], body.get("name") or (source.name[:190] + " 副本"))
    copy = models.Template(id=models.gen_uuid(), name=name, note=source.note, created_by=user.id)
    db.add(copy)
    db.flush()
    for row in template_rows(db, source.id):
        db.add(models.TemplateRow(template_id=copy.id, created_by=user.id, kind=row.kind, stage=row.stage, name=row.name,
                                  spec=row.spec, quantity=row.quantity, unit=row.unit, sort_order=row.sort_order))
    log_change(db, None, "template", copy.id, "create", user, f"复制模板 {source.name}", row_label=copy.name)
    db.commit()
    return template_dict(copy)


def type_dict(row: models.VehicleType) -> dict:
    return {"id": row.id, "name": row.name, "note": row.note, "is_enabled": row.is_enabled, "sort_order": row.sort_order}


def _type_name(db: Session, value, row_id: str = "") -> str:
    name = records.clean(records.F("text", "型号", 100, True), value)
    if db.query(models.VehicleType.id).filter(models.VehicleType.name == name, models.VehicleType.id != row_id).first():
        raise HTTPException(400, f"型号 {name} 已存在")
    return name


@router.get("/vehicle-types")
def list_types(_: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [type_dict(row) for row in db.query(models.VehicleType).order_by(models.VehicleType.sort_order, models.VehicleType.name)]


@router.post("/vehicle-types")
def create_type(body: dict = Body(...), user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    highest = db.query(func.max(models.VehicleType.sort_order)).scalar() or 0
    row = models.VehicleType(name=_type_name(db, body.get("name")), sort_order=highest + 1,
                             note=records.clean(records.F("text", "备注"), body.get("note")))
    db.add(row)
    db.flush()
    log_change(db, None, "vehicle_type", row.id, "create", user, "新增车型", row_label=row.name)
    db.commit()
    return type_dict(row)


@router.patch("/vehicle-types/{type_id}")
def update_type(type_id: str, body: dict = Body(...), user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(models.VehicleType, type_id)
    if row is None:
        raise HTTPException(404, "车型不存在")
    old = {}
    if "name" in body and (name := _type_name(db, body["name"], row.id)) != row.name:
        old["name"], row.name = row.name, name
    if "note" in body and (note := records.clean(records.F("text", "备注"), body["note"])) != row.note:
        old["note"], row.note = row.note, note
    if "is_enabled" in body:
        enabled = records.clean(records.F("bool", "启用"), body["is_enabled"])
        if enabled != row.is_enabled:
            old["is_enabled"], row.is_enabled = row.is_enabled, enabled
    if old:
        log_change(db, None, "vehicle_type", row.id, "update", user, "修改车型", old_value=old,
                   new_value={name: getattr(row, name) for name in old}, row_label=row.name)
        db.commit()
    return type_dict(row)


@router.delete("/vehicle-types/{type_id}")
def delete_type(type_id: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(models.VehicleType, type_id)
    if row is not None:
        log_change(db, None, "vehicle_type", row.id, "delete", user, "删除车型", row_label=row.name)
        db.delete(row)
        db.commit()
    return {"id": type_id, "deleted": True}
