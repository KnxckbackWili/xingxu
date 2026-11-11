"""The history: who changed what, newest first. Nothing here can be edited or removed."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.deps import get_current_user
from app.records import KINDS, PROJECT_FIELDS, TEMPLATE_FIELDS, iso

router = APIRouter(tags=["操作记录"])
KIND_LABELS = {**{key: kind.label for key, kind in KINDS.items()}, "project": "项目", "files": "文件",
               "template": "模板", "vehicle_type": "车型", "user": "账号", "system_backup": "备份",
               "system_update": "软件更新"}
ADMIN_KINDS = ("user", "system_backup", "system_update")
ACTIONS = {"create": "新增", "update": "修改", "delete": "删除", "restore": "恢复", "import": "导入",
           "reorder": "调整顺序", "purge": "彻底清除", "password": "改密码"}


def _field(entry: models.ChangeLog):
    fields = PROJECT_FIELDS if entry.kind == "project" else TEMPLATE_FIELDS if entry.kind == "template" \
        else KINDS[entry.kind].fields if entry.kind in KINDS else {}
    return fields.get(entry.field)


def _text(spec, value, vehicles) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if spec is not None and spec.type == "vehicle":
        return vehicles.get(value, "已删除的车辆")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value) if not isinstance(value, (dict, list)) else ""


@router.get("/history")
def history(project_id: str = "", user_id: str = "", before: int = Query(default=0, ge=0),
            limit: int = Query(default=100, ge=1, le=200),
            user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.ChangeLog)
    if project_id:
        query = query.filter(models.ChangeLog.project_id == project_id)
    if user_id:
        query = query.filter(models.ChangeLog.user_id == user_id)
    if user.role != "admin":
        query = query.filter(models.ChangeLog.kind.notin_(ADMIN_KINDS))
    if before:
        query = query.filter(models.ChangeLog.seq < before)
    entries = query.order_by(models.ChangeLog.seq.desc()).limit(limit + 1).all()
    more, entries = len(entries) > limit, entries[:limit]
    projects = {project.id: project for project in db.query(models.Project).filter(
        models.Project.id.in_({entry.project_id for entry in entries if entry.project_id}))}
    vehicle_ids = {value for entry in entries for value in (entry.old_value, entry.new_value)
                   if entry.field == "vehicle_id" and isinstance(value, str)}
    vehicles = {row.id: row.vehicle_no for row in db.query(models.Vehicle).filter(models.Vehicle.id.in_(vehicle_ids))}
    # A deleted row can be brought back while it is still in the trash; the page needs to know
    # which project or template it belongs to.
    in_trash, deleted = {}, {}
    for entry in entries:
        if entry.action == "delete" and entry.row_id:
            deleted.setdefault(entry.kind, set()).add(entry.row_id)
    for kind, ids in deleted.items():
        if kind == "files":
            model, scope = models.File, models.File.project_id
        elif kind == "template":
            model, scope = models.Template, models.Template.id
        elif kind in KINDS:
            model, scope = KINDS[kind].model, getattr(KINDS[kind].model, KINDS[kind].scope + "_id")
        else:
            continue
        in_trash.update(db.query(model.id, scope).filter(model.id.in_(ids), model.deleted_at.isnot(None)).all())
    items = []
    for entry in entries:
        spec = _field(entry)
        project = projects.get(entry.project_id)
        items.append({
            "seq": entry.seq, "created_at": iso(entry.created_at), "user_id": entry.user_id, "user_name": entry.user_name,
            "project_id": entry.project_id, "project_name": project.name if project else "",
            "kind": entry.kind, "kind_label": KIND_LABELS.get(entry.kind, entry.kind),
            "action": entry.action, "action_label": ACTIONS.get(entry.action, entry.detail or entry.action),
            "row_id": entry.row_id, "row_label": entry.row_label, "detail": entry.detail,
            "field_label": spec.label if spec else "", "old_text": _text(spec, entry.old_value, vehicles),
            "new_text": _text(spec, entry.new_value, vehicles),
            "scope_id": in_trash.get(entry.row_id) if entry.action == "delete" else None,
            "can_restore": entry.action == "delete" and entry.row_id in in_trash
                           and (project is None or project.deleted_at is None)})
    return {"items": items, "next_before": entries[-1].seq if more and entries else None}
