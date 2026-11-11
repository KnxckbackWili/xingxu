"""The editable lists. One declaration per kind; routes, snapshot, Excel and history all read it.

A change to a cell carries the value the editor saw ("from"). It is written only while the
stored value still equals it, so two people editing different cells of a row never collide and
two people editing the same cell find out.
"""
import math
import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app import models
from app.services.change_log import log_change
from app.time_utils import utcnow

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TEXT_LIMIT = 5000


@dataclass(frozen=True)
class F:
    type: str  # text / number / bool / date / vehicle / choice
    label: str
    max: int = TEXT_LIMIT
    required: bool = False
    stamp: str = ""  # bool only: "<stamp>_by" and "<stamp>_at" record who ticked it and when
    options: tuple = ()
    unique: bool = False  # among the live rows of the same project
    fixed: bool = False  # set on creation, never changed


@dataclass(frozen=True)
class Kind:
    key: str
    model: type
    label: str
    fields: dict = dataclass_field(default_factory=dict)
    scope: str = "project"  # the column "<scope>_id" names the project or template the row belongs to
    title: str = "name"
    ordered: bool = True


KINDS = {kind.key: kind for kind in (
    Kind("steps", models.ProjectStep, "车辆环节", {"name": F("text", "环节", 100, True)}),
    Kind("vehicles", models.Vehicle, "车辆", {
        "vehicle_no": F("text", "车辆编号", 100, True, unique=True), "fleet_no": F("text", "车号", 50),
        "model": F("text", "型号", 100), "config_no": F("text", "配置号", 100), "note": F("text", "备注")},
         title="vehicle_no"),
    Kind("vehicle-records", models.VehicleRecord, "车辆记录", {
        "vehicle_id": F("vehicle", "车辆", required=True, fixed=True), "happened_on": F("date", "调车时间记录"),
        "category": F("text", "分类", 50), "content": F("text", "变更内容", required=True),
        "recorded_by_name": F("text", "记录人", 100), "recorded_on": F("date", "记录时间")},
         title="content", ordered=False),
    Kind("work", models.WorkItem, "工作", {
        "stage": F("text", "阶段", 100), "name": F("text", "工作内容", 300, True), "note": F("text", "备注"),
        "done": F("bool", "做完", stamp="done")}),
    Kind("issues", models.Issue, "问题", {
        "description": F("text", "问题描述", required=True), "vehicle_id": F("vehicle", "关联车辆"),
        "resolution": F("text", "处理结果"), "is_closed": F("bool", "已关", stamp="closed")},
         title="description", ordered=False),
    Kind("documents", models.Document, "资料", {"name": F("text", "资料名称", 300, True), "note": F("text", "备注")}),
    Kind("items", models.Item, "物品", {
        "name": F("text", "名称", 300, True), "spec": F("text", "规格", 300), "quantity": F("number", "数量"),
        "unit": F("text", "单位", 30), "arrived": F("bool", "已到", stamp="arrived"), "note": F("text", "备注")}),
    Kind("rows", models.TemplateRow, "模板清单", {
        "kind": F("choice", "清单", required=True, fixed=True, options=("work", "document", "step", "item")),
        "stage": F("text", "阶段", 100), "name": F("text", "名称", 300, True), "spec": F("text", "规格", 300),
        "quantity": F("number", "数量"), "unit": F("text", "单位", 30)}, scope="template"),
)}
PROJECT_KINDS = tuple(key for key, kind in KINDS.items() if kind.scope == "project")
PROJECT_FIELDS = {"name": F("text", "项目名称", 200, True), "contract_no": F("text", "合同号", 100),
                  "customer": F("text", "客户", 200), "note": F("text", "备注"), "is_closed": F("bool", "已结束")}
TEMPLATE_FIELDS = {"name": F("text", "模板名称", 200, True), "note": F("text", "备注")}
SCOPES = {"project": models.Project, "template": models.Template}


class Conflict(Exception):
    def __init__(self, conflicts, row):
        self.conflicts, self.row = conflicts, row


def iso(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds") + ("" if value.tzinfo else "Z")
    return value.isoformat() if isinstance(value, date) else value


def clean(spec: F, value, *, db: Session = None, scope_id: str = None):
    """The stored form of a submitted value; 400 when it cannot be one."""
    label = spec.label
    if spec.type == "text":
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise HTTPException(400, f"{label}应为文字")
        value = value.strip()
        if spec.required and not value:
            raise HTTPException(400, f"请填写{label}")
        if len(value) > spec.max:
            raise HTTPException(400, f"{label}最多 {spec.max} 个字")
        return value
    if spec.type == "number":
        if value in (None, ""):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e12:
            raise HTTPException(400, f"{label}应为数字")
        return float(value)
    if spec.type == "bool":
        if not isinstance(value, bool):
            raise HTTPException(400, f"{label}应为是或否")
        return value
    if spec.type == "date":
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{label}应为日期，例如 2026-05-23") from None
    if spec.type == "choice":
        if value not in spec.options:
            raise HTTPException(400, f"{label}不正确")
        return value
    if spec.type == "vehicle":
        if value in (None, ""):
            if spec.required:
                raise HTTPException(400, f"请选择{label}")
            return None
        found = db.query(models.Vehicle.id).filter_by(id=value, project_id=scope_id, deleted_at=None).first() \
            if isinstance(value, str) else None
        if found is None:
            raise HTTPException(400, "所选车辆不存在或已删除")
        return value
    raise HTTPException(400, f"{label}不能修改")


def row_dict(kind: Kind, row) -> dict:
    data = {"id": row.id, "created_at": iso(row.created_at), "created_by": row.created_by, "updated_at": iso(row.updated_at)}
    for name, spec in kind.fields.items():
        data[name] = iso(getattr(row, name))
        if spec.stamp:
            data[spec.stamp + "_by"] = getattr(row, spec.stamp + "_by")
            data[spec.stamp + "_at"] = iso(getattr(row, spec.stamp + "_at"))
    if kind.ordered:
        data["sort_order"] = row.sort_order
    if row.deleted_at is not None:
        data["deleted_at"] = iso(row.deleted_at)
    return data


def title_of(kind: Kind, row) -> str:
    return str(getattr(row, kind.title) or "")[:300]


def bump(db: Session, scope_model, scope_id: str) -> None:
    db.execute(update(scope_model).where(scope_model.id == scope_id)
               .values(rev=scope_model.rev + 1, updated_at=utcnow()))


def load_scope(db: Session, kind_scope: str, scope_id: str):
    row = db.get(SCOPES[kind_scope], scope_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, "项目不存在或已删除" if kind_scope == "project" else "模板不存在或已删除")
    return row


def _scope_column(kind: Kind):
    return getattr(kind.model, kind.scope + "_id")


def _live(db: Session, kind: Kind, scope_id: str):
    return db.query(kind.model).filter(_scope_column(kind) == scope_id, kind.model.deleted_at.is_(None))


def _check_unique(db: Session, kind: Kind, scope_id: str, name: str, value, row_id: str) -> None:
    clash = _live(db, kind, scope_id).filter(getattr(kind.model, name) == value, kind.model.id != row_id).first()
    if clash is not None:
        raise HTTPException(400, f"{kind.fields[name].label} {value} 已存在")


def _next_order(db: Session, kind: Kind, scope_id: str) -> int:
    highest = db.query(func.max(kind.model.sort_order)).filter(_scope_column(kind) == scope_id).scalar()
    return (highest or 0) + 1


def _stamp(row, spec: F, value: bool, user) -> None:
    if spec.stamp:
        setattr(row, spec.stamp + "_by", user.id if value else None)
        setattr(row, spec.stamp + "_at", utcnow() if value else None)


def create(db: Session, user, kind: Kind, scope_id: str, body: dict, *, action: str = "create"):
    """Add a row. The client names it (a UUID), so a repeated request returns the same row."""
    row_id = body.get("id")
    if row_id is not None:
        if not isinstance(row_id, str) or not _UUID.match(row_id):
            raise HTTPException(400, "记录编号格式不正确")
        existing = db.get(kind.model, row_id)
        if existing is not None:
            if getattr(existing, kind.scope + "_id") != scope_id or existing.deleted_at is not None:
                raise HTTPException(409, "记录编号已被占用")
            return existing, False
    unknown = set(body) - set(kind.fields) - {"id"}
    if unknown:
        raise HTTPException(400, "不认识的栏目：" + "、".join(sorted(unknown)))
    row = kind.model(**{kind.scope + "_id": scope_id}, created_by=user.id)
    if row_id:
        row.id = row_id
    else:
        row.id = models.gen_uuid()
    for name, spec in kind.fields.items():
        if name not in body and not spec.required:
            continue
        value = clean(spec, body.get(name), db=db, scope_id=scope_id)
        if spec.unique:
            _check_unique(db, kind, scope_id, name, value, row.id)
        setattr(row, name, value)
        if spec.type == "bool":
            _stamp(row, spec, value, user)
    if kind.ordered:
        row.sort_order = _next_order(db, kind, scope_id)
    db.add(row)
    db.flush()
    log_change(db, scope_id if kind.scope == "project" else None, kind.key, row.id, action, user,
               f"新增{kind.label}", new_value={name: iso(getattr(row, name)) for name in kind.fields},
               row_label=title_of(kind, row))
    bump(db, SCOPES[kind.scope], scope_id)
    return row, True


def last_editor(db: Session, row_id: str, name: str) -> str:
    entry = (db.query(models.ChangeLog).filter_by(row_id=row_id, field=name)
             .order_by(models.ChangeLog.seq.desc()).first())
    return entry.user_name if entry else ""


def apply_changes(db: Session, user, row, fields: dict, changes: dict, *, scope_id: str, kind_key: str,
                  label: str, row_label: str, project_id, unique=None) -> bool:
    """Compare every submitted "from" with the stored value; write all changes or none."""
    if not isinstance(changes, dict) or not changes:
        raise HTTPException(400, "没有要保存的内容")
    planned, conflicts = [], {}
    for name, change in changes.items():
        spec = fields.get(name)
        if spec is None or spec.fixed:
            raise HTTPException(400, f"不能修改的栏目：{name}")
        if not isinstance(change, dict) or "to" not in change:
            raise HTTPException(400, "保存内容格式不正确")
        new = clean(spec, change["to"], db=db, scope_id=scope_id)
        current = getattr(row, name)
        if "from" in change:
            if spec.type == "vehicle":
                seen = change["from"] or None
            else:
                try:
                    seen = clean(F(spec.type, spec.label, spec.max, options=spec.options), change["from"])
                except HTTPException:
                    seen = object()  # a value that could never be stored matches nothing
            if seen != current and new != current:
                conflicts[name] = {"current": iso(current), "by": last_editor(db, row.id, name)}
                continue
        if new != current:
            planned.append((name, spec, current, new))
    if conflicts:
        raise Conflict(conflicts, row)
    for name, spec, current, new in planned:
        if spec.unique and unique is not None:
            unique(name, new)
        setattr(row, name, new)
        if spec.type == "bool":
            _stamp(row, spec, new, user)
        log_change(db, project_id, kind_key, row.id, "update", user, f"修改{label}的{spec.label}",
                   old_value=iso(current), new_value=iso(new), field=name, row_label=row_label)
    return bool(planned)


def patch(db: Session, user, kind: Kind, scope_id: str, row_id: str, changes: dict):
    row = _live(db, kind, scope_id).filter(kind.model.id == row_id).with_for_update().first()
    if row is None:
        raise HTTPException(404, f"这条{kind.label}不存在或已被删除")
    changed = apply_changes(
        db, user, row, kind.fields, changes, scope_id=scope_id, kind_key=kind.key, label=kind.label,
        row_label=title_of(kind, row), project_id=scope_id if kind.scope == "project" else None,
        unique=lambda name, value: _check_unique(db, kind, scope_id, name, value, row.id))
    if changed:
        row.updated_at = utcnow()
        bump(db, SCOPES[kind.scope], scope_id)
    return row


def remove(db: Session, user, kind: Kind, scope_id: str, row_id: str):
    row = _live(db, kind, scope_id).filter(kind.model.id == row_id).with_for_update().first()
    if row is None:
        return None  # already gone: deleting twice is not an error
    row.deleted_at = utcnow()
    log_change(db, scope_id if kind.scope == "project" else None, kind.key, row.id, "delete", user,
               f"删除{kind.label}", row_label=title_of(kind, row))
    bump(db, SCOPES[kind.scope], scope_id)
    return row


def restore(db: Session, user, kind: Kind, scope_id: str, row_id: str):
    row = db.query(kind.model).filter(_scope_column(kind) == scope_id, kind.model.id == row_id).with_for_update().first()
    if row is None:
        raise HTTPException(404, f"这条{kind.label}已被彻底清除，无法恢复")
    if row.deleted_at is None:
        return row
    for name, spec in kind.fields.items():
        if spec.unique:
            _check_unique(db, kind, scope_id, name, getattr(row, name), row.id)
        if spec.type == "vehicle" and getattr(row, name):
            alive = db.query(models.Vehicle.id).filter_by(id=getattr(row, name), deleted_at=None).first()
            if alive is None and spec.required:
                raise HTTPException(400, "这条记录所属的车辆已删除，请先恢复车辆")
            if alive is None:
                setattr(row, name, None)
    row.deleted_at = None
    log_change(db, scope_id if kind.scope == "project" else None, kind.key, row.id, "restore", user,
               f"恢复{kind.label}", row_label=title_of(kind, row))
    bump(db, SCOPES[kind.scope], scope_id)
    return row


def reorder(db: Session, user, kind: Kind, scope_id: str, ids) -> None:
    if not kind.ordered:
        raise HTTPException(400, f"{kind.label}不支持调整顺序")
    if not isinstance(ids, list) or len(set(ids)) != len(ids):
        raise HTTPException(400, "顺序内容不正确")
    rows = {row.id: row for row in _live(db, kind, scope_id).all()}
    if any(row_id not in rows for row_id in ids):
        raise HTTPException(409, "列表已变化，请稍后重试")
    # Rows added meanwhile by someone else keep their place after the submitted ones.
    rest = sorted((row for row_id, row in rows.items() if row_id not in set(ids)), key=lambda row: row.sort_order)
    for position, row in enumerate([rows[row_id] for row_id in ids] + rest, start=1):
        row.sort_order = position
    log_change(db, scope_id if kind.scope == "project" else None, kind.key, "", "reorder", user, f"调整{kind.label}顺序")
    bump(db, SCOPES[kind.scope], scope_id)
