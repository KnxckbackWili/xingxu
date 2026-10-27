"""Project-site inventory with ownership and movement history."""

from datetime import date, datetime, timezone
from app.services.system_permissions import route_permission
from app.time_utils import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Project, ProjectInventoryItem, ProjectInventoryMovement, User
from app.services.change_log import log_change
from app.services.inventory_time import inventory_time_basis
from app.services.record_lock import lock_record, lock_writable_project
from app.services.permissions import C_INVENTORY, require_project_capability, authorize_project
from app.services.scope import ensure_project_visible, visible_project_ids

router = APIRouter(tags=["物品管理"])

OWNERSHIPS = {"company", "client", "third_party"}
CATEGORIES = {"equipment", "tool", "spare_part", "material", "consumable", "document", "other"}
STATUSES = {"expected", "in_transit", "on_site", "in_use", "loaned", "consumed", "returned", "lost", "damaged", "scrapped"}
MOVEMENT_TYPES = {"receive", "issue", "transfer", "consume", "return_owner", "return_site", "adjust", "inventory"}


class ItemBody(BaseModel):
    model_config = {"extra": "forbid"}

    item_code: str = Field(default="", max_length=100)
    name: str = Field(min_length=1, max_length=200)
    category: str = "other"
    ownership: str = "company"
    tracking_mode: str = "quantity"
    specification: str = Field(default="", max_length=300)
    serial_number: str = Field(default="", max_length=200)
    quantity: float = Field(default=0, ge=0, le=1_000_000_000)
    minimum_quantity: Optional[float] = Field(default=None, ge=0, le=1_000_000_000)
    unit: str = Field(default="件", min_length=1, max_length=20)
    status: str = "on_site"
    location: str = Field(default="", max_length=200)
    custodian: str = Field(default="", max_length=100)
    supplier: str = Field(default="", max_length=200)
    received_date: Optional[date] = None
    expected_return_date: Optional[date] = None
    note: str = Field(default="", max_length=5000)
    extra: dict = Field(default_factory=dict)

    @field_validator("category")
    @classmethod
    def category_valid(cls, value):
        if value not in CATEGORIES:
            raise ValueError("物品分类无效")
        return value

    @field_validator("name", "unit")
    @classmethod
    def required_text_valid(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("名称和单位不能为空")
        return value

    @field_validator("ownership")
    @classmethod
    def ownership_valid(cls, value):
        if value not in OWNERSHIPS:
            raise ValueError("物品归属无效")
        return value

    @field_validator("tracking_mode")
    @classmethod
    def tracking_valid(cls, value):
        if value not in {"quantity", "serial"}:
            raise ValueError("管理方式无效")
        return value

    @field_validator("status")
    @classmethod
    def status_valid(cls, value):
        if value not in STATUSES:
            raise ValueError("物品状态无效")
        return value


class ItemStatusUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    status: str
    expected_status: str

    @field_validator("status", "expected_status")
    @classmethod
    def valid_status(cls, value):
        if value not in STATUSES:
            raise ValueError("物品状态无效")
        return value


class MovementBody(BaseModel):
    model_config = {"extra": "forbid"}

    client_uuid: Optional[str] = Field(default=None, min_length=8, max_length=64)
    movement_type: str
    quantity: float = Field(default=0, ge=0, le=1_000_000_000)
    quantity_after: Optional[float] = Field(default=None, ge=0, le=1_000_000_000)
    from_location: str = Field(default="", max_length=200)
    to_location: str = Field(default="", max_length=200)
    handler: str = Field(default="", max_length=100)
    occurred_at: datetime = Field(default_factory=utcnow)
    note: str = Field(default="", max_length=5000)

    @field_validator("movement_type")
    @classmethod
    def movement_valid(cls, value):
        if value not in MOVEMENT_TYPES:
            raise ValueError("流水类型无效")
        return value

    _time_basis: str = PrivateAttr(default="utc")

    @model_validator(mode="after")
    def occurred_at_utc(self):
        # Old clients sent a local wall-clock value. Preserve it explicitly;
        # aware timestamps and server defaults have a known UTC basis.
        if self.occurred_at.tzinfo:
            self.occurred_at = self.occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
        elif "occurred_at" in self.model_fields_set:
            self._time_basis = "legacy_local"
        return self


class BulkImportBody(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[ItemBody] = Field(min_length=1, max_length=500)


def _item_dict(item: ProjectInventoryItem, project_name: str = "", movement_count: int = 0) -> dict:
    return {
        "id": item.id, "project_id": item.project_id, "project_name": project_name,
        "item_code": item.item_code, "name": item.name, "category": item.category,
        "ownership": item.ownership, "tracking_mode": item.tracking_mode,
        "specification": item.specification, "serial_number": item.serial_number,
        "quantity": item.quantity, "minimum_quantity": item.minimum_quantity, "unit": item.unit,
        "status": item.status, "location": item.location, "custodian": item.custodian,
        "supplier": item.supplier,
        "received_date": item.received_date.isoformat() if item.received_date else None,
        "expected_return_date": item.expected_return_date.isoformat() if item.expected_return_date else None,
        "note": item.note, "extra": item.extra or {}, "movement_count": movement_count,
        "low_stock": item.minimum_quantity is not None and item.quantity <= item.minimum_quantity,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _movement_dict(row: ProjectInventoryMovement, operator_name: str = "") -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "item_id": row.item_id,
        "movement_type": row.movement_type, "quantity": row.quantity,
        "balance_after": row.balance_after, "from_location": row.from_location,
        "to_location": row.to_location, "handler": row.handler,
        "occurred_at": row.occurred_at.isoformat(), "time_basis": inventory_time_basis(row), "note": row.note,
        "operator_id": row.operator_id, "operator_name": operator_name,
    }


def _list_items(
    db: Session, project_ids: list[str], page: int, page_size: int, search: str,
    ownership: str, status: str, category: str, project_id: str = "",
) -> dict:
    query = db.query(ProjectInventoryItem).filter(ProjectInventoryItem.project_id.in_(project_ids or ["__none__"]))
    if project_id:
        query = query.filter(ProjectInventoryItem.project_id == project_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(or_(
            ProjectInventoryItem.name.ilike(like), ProjectInventoryItem.item_code.ilike(like),
            ProjectInventoryItem.specification.ilike(like), ProjectInventoryItem.serial_number.ilike(like),
            ProjectInventoryItem.location.ilike(like), ProjectInventoryItem.custodian.ilike(like),
        ))
    if ownership:
        query = query.filter(ProjectInventoryItem.ownership == ownership)
    if status:
        query = query.filter(ProjectInventoryItem.status == status)
    if category:
        query = query.filter(ProjectInventoryItem.category == category)
    total = query.count()
    rows = query.order_by(ProjectInventoryItem.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    project_names = {p.id: p.name for p in db.query(Project).filter(Project.id.in_(project_ids or ["__none__"])).all()}
    counts = dict(db.query(ProjectInventoryMovement.item_id, func.count(ProjectInventoryMovement.id))
                  .filter(ProjectInventoryMovement.item_id.in_([row.id for row in rows] or ["__none__"]))
                  .group_by(ProjectInventoryMovement.item_id).all())
    summary_base = ProjectInventoryItem.project_id.in_(project_ids or ["__none__"])
    summary_row = db.query(
        func.count(ProjectInventoryItem.id),
        func.count(func.distinct(ProjectInventoryItem.project_id)),
        func.sum(case((ProjectInventoryItem.ownership == "company", 1), else_=0)),
        func.sum(case((ProjectInventoryItem.ownership == "client", 1), else_=0)),
        func.sum(case((or_(
            ProjectInventoryItem.status.in_(("lost", "damaged")),
            (ProjectInventoryItem.minimum_quantity.is_not(None))
            & (ProjectInventoryItem.quantity <= ProjectInventoryItem.minimum_quantity),
        ), 1), else_=0)),
    ).filter(summary_base).one()
    summary = {
        "total_records": summary_row[0] or 0,
        "project_count": summary_row[1] or 0,
        "company_records": summary_row[2] or 0,
        "client_records": summary_row[3] or 0,
        "attention_records": summary_row[4] or 0,
    }
    return {
        "items": [_item_dict(row, project_names.get(row.project_id, ""), counts.get(row.id, 0)) for row in rows],
        "total": total, "page": page, "page_size": page_size, "summary": summary,
    }


@router.get("/inventory")
@route_permission('system.inventory.read')
def global_inventory(
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), search: str = "",
    ownership: str = "", status: str = "", category: str = "", project_id: str = "",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ids = visible_project_ids(db, user)
    if project_id and project_id not in ids:
        raise HTTPException(status_code=404, detail="项目不存在")
    return _list_items(db, ids, page, page_size, search, ownership, status, category, project_id)


@router.get("/projects/{project_id}/inventory")
@route_permission('project.read')
def project_inventory(
    project_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
    search: str = "", ownership: str = "", status: str = "", category: str = "",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ensure_project_visible(db, project_id, user)
    return _list_items(db, [project_id], page, page_size, search, ownership, status, category, project_id)


@router.post("/projects/{project_id}/inventory")
@route_permission('project.manage_inventory')
def create_item(
    project_id: str, body: ItemBody,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    project = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, project, user)
    authorize_project(user, project, C_INVENTORY)
    if body.tracking_mode == "serial" and body.quantity not in (0, 1):
        raise HTTPException(status_code=400, detail="按序列号管理的物品数量只能是 0 或 1")
    item = ProjectInventoryItem(project_id=project_id, created_by=user.id, **body.model_dump())
    db.add(item)
    db.flush()
    if item.quantity:
        db.add(ProjectInventoryMovement(
            project_id=project_id, item_id=item.id, movement_type="inventory",
            quantity=item.quantity, balance_after=item.quantity, to_location=item.location,
            handler=item.custodian, note="建立台账时的初始数量", operator_id=user.id,
        ))
    log_change(db, project_id, "inventory_item", item.id, "create", user.id, f"新增物品「{item.name}」")
    db.commit()
    return _item_dict(item)


@router.post("/projects/{project_id}/inventory/import")
@route_permission('project.manage_inventory')
def import_items(
    project_id: str, body: BulkImportBody,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    project = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, project, user)
    authorize_project(user, project, C_INVENTORY)
    created = []
    for item_body in body.items:
        if item_body.tracking_mode == "serial" and item_body.quantity not in (0, 1):
            raise HTTPException(status_code=400, detail=f"物品「{item_body.name}」按序列号管理，数量只能是 0 或 1")
        item = ProjectInventoryItem(project_id=project_id, created_by=user.id, **item_body.model_dump())
        db.add(item)
        db.flush()
        if item.quantity:
            db.add(ProjectInventoryMovement(
                project_id=project_id, item_id=item.id, movement_type="inventory",
                quantity=item.quantity, balance_after=item.quantity, to_location=item.location,
                handler=item.custodian, note="批量导入时的初始数量", operator_id=user.id,
            ))
        created.append(item)
    log_change(db, project_id, "inventory_item", project_id, "import", user.id, f"批量导入现场物品 {len(created)} 条")
    db.commit()
    return {"message": f"已导入 {len(created)} 条现场物品", "count": len(created)}


@router.put("/projects/{project_id}/inventory/{item_id}")
@route_permission('project.manage_inventory')
def update_item(
    project_id: str, item_id: str, body: ItemBody,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    project = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, project, user)
    authorize_project(user, project, C_INVENTORY)
    item = db.get(ProjectInventoryItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品不存在")
    if body.tracking_mode == "serial" and body.quantity not in (0, 1):
        raise HTTPException(status_code=400, detail="按序列号管理的物品数量只能是 0 或 1")
    lock_record(db, item, conflict_detail="物品正由另一操作更新，请刷新后重试")
    old_quantity = item.quantity
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    if old_quantity != item.quantity:
        db.add(ProjectInventoryMovement(
            project_id=project_id, item_id=item.id, movement_type="adjust",
            quantity=abs(item.quantity - old_quantity), balance_after=item.quantity,
            to_location=item.location, handler=item.custodian, note="编辑台账时调整数量", operator_id=user.id,
        ))
    log_change(db, project_id, "inventory_item", item.id, "update", user.id, f"更新物品「{item.name}」")
    db.commit()
    return _item_dict(item)


@router.patch("/projects/{project_id}/inventory/{item_id}/status")
@route_permission('project.manage_inventory')
def update_item_status(
    project_id: str, item_id: str, body: ItemStatusUpdate,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    project = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, project, user)
    authorize_project(user, project, C_INVENTORY)
    item = db.get(ProjectInventoryItem, item_id, populate_existing=True)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品不存在")
    lock_record(db, item, conflict_detail="物品正由另一操作更新，请刷新后重试")
    if item.status != body.expected_status:
        raise HTTPException(status_code=409, detail="物品状态已被其他人修改，请刷新后重新选择")
    if item.status != body.status:
        item.status = body.status
        log_change(db, project_id, "inventory_item", item.id, "update", user.id, f"快捷更新物品「{item.name}」状态")
    db.commit()
    return _item_dict(item)


@router.delete("/projects/{project_id}/inventory/{item_id}")
@route_permission('project.manage_inventory')
def delete_item(
    project_id: str, item_id: str,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    project = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, project, user)
    authorize_project(user, project, C_INVENTORY)
    item = db.get(ProjectInventoryItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品不存在")
    lock_record(db, item, conflict_detail="物品正由另一操作更新，请刷新后重试")
    name = item.name
    db.delete(item)
    log_change(db, project_id, "inventory_item", item_id, "delete", user.id, f"删除物品「{name}」及其流水")
    db.commit()
    return {"message": "物品已删除"}


@router.get("/projects/{project_id}/inventory/{item_id}/movements")
@route_permission('project.read')
def list_movements(
    project_id: str, item_id: str,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ensure_project_visible(db, project_id, user)
    item = db.get(ProjectInventoryItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品不存在")
    rows = db.query(ProjectInventoryMovement).filter_by(item_id=item_id).order_by(ProjectInventoryMovement.occurred_at.desc()).all()
    names = {u.id: u.display_name for u in db.query(User).filter(User.id.in_([r.operator_id for r in rows if r.operator_id] or ["__none__"])).all()}
    return [_movement_dict(row, names.get(row.operator_id, "")) for row in rows]


@router.post("/projects/{project_id}/inventory/{item_id}/movements")
@route_permission('project.manage_inventory')
def create_movement(
    project_id: str, item_id: str, body: MovementBody,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    project = ensure_project_visible(db, project_id, user)
    # Confirm a saved retry even if the project was archived afterward; only a
    # genuinely new movement needs the writable-state gate below.
    from app.services.record_lock import lock_record
    lock_record(db, project, conflict_detail="项目正由另一操作更新，请稍后重试")
    project = ensure_project_visible(db, project_id, user)
    authorize_project(user, project, C_INVENTORY)
    item = db.get(ProjectInventoryItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品不存在")
    lock_record(db, item, conflict_detail="物品正由另一操作更新，请刷新后重试")
    receipt_key = None
    if body.client_uuid:
        import hashlib
        import json
        from app.models import OfflineOpReceipt
        receipt_key = hashlib.sha256(json.dumps([item_id, body.client_uuid], separators=(",", ":")).encode()).hexdigest()
        receipt = db.query(OfflineOpReceipt).filter_by(user_id=user.id, project_id=project_id,
            op_type="inventory_movement", client_uuid=receipt_key).first()
        if receipt is not None:
            prior = db.get(ProjectInventoryMovement, receipt.id)
            if prior is None or prior.item_id != item_id:
                raise HTTPException(409, "该流水操作已处理但记录已变化，请刷新台账核对")
            same_quantity = (prior.balance_after == body.quantity_after
                             if body.movement_type in {"adjust", "inventory"} else prior.quantity == body.quantity)
            same_fields = all(getattr(prior, key) == getattr(body, key) for key in
                              ("movement_type", "from_location", "to_location", "handler", "note"))
            same_time = ("occurred_at" not in body.model_fields_set
                         or (prior.occurred_at.replace(tzinfo=None) == body.occurred_at.replace(tzinfo=None)
                             and inventory_time_basis(prior) == body._time_basis))
            if not same_quantity or not same_fields or not same_time:
                raise HTTPException(409, "同一流水操作编号的内容已变化，请刷新核对原流水后再创建新操作")
            return {"item": _item_dict(item), "movement": _movement_dict(prior, user.display_name), "accepted": False}
    from app.services.project_lifecycle import ensure_project_writable
    ensure_project_writable(project)
    before = float(item.quantity or 0)
    # Decimal-from-text avoids a 0.3 - 0.1 balance becoming smaller than
    # the later 0.2 withdrawal. A tiny tolerance also accepts legacy drift.
    from decimal import Decimal
    exact_before, exact_quantity = Decimal(str(before)), Decimal(str(body.quantity))
    if body.movement_type in {"receive", "return_site"}:
        if before > 0 and body.to_location and item.location and body.to_location != item.location:
            raise HTTPException(400, "已有库存与本次入库地点不同，请先拆分物品台账，不能合并为同一位置的库存")
        after = float(exact_before + exact_quantity)
    elif body.movement_type in {"issue", "consume", "return_owner"}:
        if body.quantity > before + 1e-9:
            raise HTTPException(status_code=400, detail=f"当前仅有 {before:g}{item.unit}，不能减少 {body.quantity:g}{item.unit}")
        after = max(0.0, float(exact_before - exact_quantity))
    elif body.movement_type in {"adjust", "inventory"}:
        if body.quantity_after is None:
            raise HTTPException(status_code=400, detail="盘点或调整必须填写调整后数量")
        after = body.quantity_after
    else:
        if abs(body.quantity - before) > 1e-9:
            raise HTTPException(400, "位置转移仅支持整条台账的全部数量；部分转移请先拆分物品台账，再分别记录位置")
        after = before
    if after > 1_000_000_000:
        raise HTTPException(400, "流水后库存数量超过允许的上限")
    if item.tracking_mode == "serial" and after not in (0, 1):
        raise HTTPException(status_code=400, detail="按序列号管理的物品数量只能是 0 或 1")
    item.quantity = after
    # Outgoing destinations/handlers describe the removed goods. The stock
    # still on this record stays at its original location with its custodian.
    update_stock_metadata = (body.movement_type in {"transfer", "adjust", "inventory"}
                             or (body.movement_type in {"receive", "return_site"} and before == 0))
    if update_stock_metadata:
        if body.to_location:
            item.location = body.to_location
        if body.handler:
            item.custodian = body.handler
    if body.movement_type == "consume" and after == 0:
        item.status = "consumed"
    elif body.movement_type == "return_owner" and after == 0:
        item.status = "returned"
    elif body.movement_type in {"receive", "return_site"} and after > 0 and item.status in {"expected", "in_transit", "returned", "consumed"}:
        item.status = "on_site"
    movement = ProjectInventoryMovement(
        project_id=project_id, item_id=item_id, movement_type=body.movement_type,
        quantity=body.quantity if body.movement_type not in {"adjust", "inventory"} else abs(after - before),
        balance_after=after, from_location=body.from_location, to_location=body.to_location,
        handler=body.handler, occurred_at=body.occurred_at, time_basis=body._time_basis, note=body.note, operator_id=user.id,
    )
    db.add(movement)
    db.flush()
    if receipt_key:
        # Receipt and business movement share an ID for deterministic replay;
        # both commit atomically with the balance and audit, no schema change.
        from app.models import OfflineOpReceipt
        db.add(OfflineOpReceipt(id=movement.id, user_id=user.id, project_id=project_id,
            op_type="inventory_movement", client_uuid=receipt_key))
    log_change(db, project_id, "inventory_item", item.id, "update", user.id, f"物品「{item.name}」新增流水：{body.movement_type}")
    db.commit()
    return {"item": _item_dict(item), "movement": _movement_dict(movement, user.display_name), "accepted": True}
