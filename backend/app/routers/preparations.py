"""项目采购清单：从常用采购项库带入或手工添加，跟进到货。

写 = project.manage_plan；读 = 项目可见。所有修改 log_change() 留痕。
"""

from datetime import date
from app.services.system_permissions import route_permission
from app.time_utils import utcnow
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Project, ProjectPreparationItem, User
from app.services.scope import ensure_project_visible
from app.services.permissions import authorize_project, C_PLAN
from app.services.change_log import log_change
from app.services.project_events import planned_event_date

router = APIRouter(tags=["准备"])

STATUS_LABEL = {
    "not_started": "未开始", "in_progress": "进行中", "pending": "待确认",
    "passed": "已通过", "failed": "不通过", "na": "不适用",
}


class PrepItemCreate(BaseModel):
    category: str = Field(default="procurement", pattern="^procurement$")
    name: str = Field(..., min_length=1, max_length=200)
    is_required: bool = False
    status: str = Field(default="not_started",
                        pattern="^(not_started|in_progress|pending|passed|failed|na)$")
    owner_id: Optional[str] = None  # 内部跟进人
    owner_party: str = Field(default="project",
                             pattern="^(project|client|procurement|production|software|company)$")
    required_date: Optional[date] = None  # 项目要求日期
    committed_date: Optional[date] = None  # 责任方承诺日期
    forecast_date: Optional[date] = None  # 当前预计日期
    actual_date: Optional[date] = None
    risk: str = Field(default="low", pattern="^(low|medium|high)$")
    note: str = ""
    extra: Optional[dict] = None


class PrepItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    is_required: Optional[bool] = None
    status: Optional[str] = Field(default=None,
                                  pattern="^(not_started|in_progress|pending|passed|failed|na)$")
    owner_id: Optional[str] = None
    owner_party: Optional[str] = Field(default=None, pattern="^(project|client|procurement|production|software|company)$")
    required_date: Optional[date] = None
    committed_date: Optional[date] = None
    forecast_date: Optional[date] = None
    actual_date: Optional[date] = None
    risk: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")
    note: Optional[str] = None
    extra: Optional[dict] = None


def _writable_preparation_project(db: Session, project_id: str, user: User) -> Project:
    p = ensure_project_visible(db, project_id, user)
    authorize_project(user, p, C_PLAN)
    from app.services.record_lock import lock_writable_project
    p = lock_writable_project(db, p, user)
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    authorize_project(user, p, C_PLAN)
    return p


def _record_preparation_completion(item, project, user, previous_status=None):
    """Completion attribution follows the current passed state; logs retain history."""
    from app.time_utils import project_today
    today = project_today(project.timezone)
    if item.actual_date is not None and item.actual_date > today:
        raise HTTPException(400, f"实际完成日期不能晚于现场今天（{today.isoformat()}）；未来安排请填写当前预计日期")
    if item.status == "passed":
        if item.actual_date is None:
            item.actual_date = today
        if previous_status != "passed" or not item.completed_by:
            item.completed_by = user.id
            item.completed_at = utcnow()
    elif previous_status == "passed":
        item.actual_date = None
        item.completed_by = None
        item.completed_at = None


def _preparation_passed(item, today):
    return item.status == "passed" and (item.actual_date is None or item.actual_date <= today)


def _validate_owner(db: Session, owner_id: Optional[str]) -> None:
    if owner_id:
        person = db.get(User, owner_id)
        if person is None or not person.is_active:
            raise HTTPException(status_code=400, detail="内部跟进人必须是启用的系统用户")


def _item_dict(db: Session, i: ProjectPreparationItem) -> dict:
    owner = db.get(User, i.owner_id) if i.owner_id else None
    return {
        "id": i.id,
        "category": i.category,
        "name": i.name,
        "is_required": i.is_required,
        "status": i.status,
        "owner_id": i.owner_id,
        "owner_name": owner.display_name if owner else "",
        "owner_party": i.owner_party,
        "required_date": i.required_date.isoformat() if i.required_date else None,
        "committed_date": i.committed_date.isoformat() if i.committed_date else None,
        "forecast_date": i.forecast_date.isoformat() if i.forecast_date else None,
        "actual_date": i.actual_date.isoformat() if i.actual_date else None,
        "risk": i.risk,
        "completed_by": i.completed_by,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "note": i.note,
        "extra": i.extra or {},
        "sort_order": i.sort_order,
    }


def _procurement_summary(db: Session, project: Project) -> dict:
    from app.time_utils import project_today
    today = project_today(project.timezone)
    items = db.query(ProjectPreparationItem).filter_by(project_id=project.id, category='procurement').all()
    passed = [row for row in items if _preparation_passed(row, today)]
    pending = [row for row in items if row.status != 'na' and row not in passed]
    ship = planned_event_date(db, project.id)
    return {'total': len(items), 'done': len(passed), 'today': today.isoformat(),
        'required_total': sum(row.is_required and row.status != 'na' for row in items),
        'required_done': sum(row.is_required for row in passed),
        'overdue': sum(bool(row.required_date) and row.required_date < today for row in pending),
        'planned_ship_date': ship.isoformat() if ship else None}


class ProcurementImportItem(BaseModel):
    item_id: str
    quantity: float = Field(allow_inf_nan=False, default=1, gt=0)


class ProcurementImportBody(BaseModel):
    items: list[ProcurementImportItem] = Field(default_factory=list, max_length=100)


@router.post("/projects/{project_id}/procurements/import")
@route_permission('project.manage_plan')
def import_procurements(project_id: str, data: ProcurementImportBody,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """从常用采购项库显式带入项目；数量在项目内确认后写入。"""
    from app.models import TemplateProcurementItem

    project = _writable_preparation_project(db, project_id, user)
    if not data.items:
        return {"created": 0, "skipped": 0}

    id_map = {item.item_id: item.quantity for item in data.items}
    rows = db.query(TemplateProcurementItem).filter(
        TemplateProcurementItem.id.in_(id_map.keys())
    ).order_by(TemplateProcurementItem.sort_order).all()
    existing_names = {
        name for (name,) in db.query(ProjectPreparationItem.name).filter(
            ProjectPreparationItem.project_id == project_id,
            ProjectPreparationItem.category == "procurement",
        ).all()
    }
    sort_order = db.query(ProjectPreparationItem).filter(
        ProjectPreparationItem.project_id == project_id
    ).count()
    created = 0
    for row in rows:
        if row.name in existing_names:
            continue
        item = ProjectPreparationItem(
            project_id=project_id,
            category="procurement",
            name=row.name,
            is_required=row.is_required,
            owner_party="procurement",
            required_date=planned_event_date(db, project.id),
            risk=row.risk,
            extra={
                "quantity": id_map.get(row.id, 1),
                "unit": row.unit,
                "spec": row.spec,
                "order_status": "未申请",
                "source": "catalog",
            },
            sort_order=sort_order + created,
        )
        db.add(item)
        existing_names.add(row.name)
        created += 1
    log_change(db, project_id, "preparation", project_id, "create", user.id,
               f"从常用采购项库带入 {created} 项")
    db.commit()
    return {"created": created, "skipped": len(rows) - created}


@router.get("/projects/{project_id}/procurements")
@route_permission('project.read')
def list_preparations(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """采购清单 + 状态摘要（项目可见即可读）。"""
    p = ensure_project_visible(db, project_id, user)
    items = db.query(ProjectPreparationItem).filter(
        ProjectPreparationItem.project_id == project_id, ProjectPreparationItem.category == "procurement").order_by(
        ProjectPreparationItem.sort_order, ProjectPreparationItem.created_at).all()
    return {
        "summary": _procurement_summary(db, p),
        "items": [_item_dict(db, i) for i in items],
    }


@router.post("/projects/{project_id}/procurements")
@route_permission('project.manage_plan')
def create_item(project_id: str, data: PrepItemCreate,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _writable_preparation_project(db, project_id, user)
    _validate_owner(db, data.owner_id)
    max_sort = db.query(ProjectPreparationItem).filter(
        ProjectPreparationItem.project_id == project_id).count()
    i = ProjectPreparationItem(project_id=project_id, sort_order=max_sort, **data.model_dump())
    _record_preparation_completion(i, p, user)
    db.add(i)
    db.flush()
    log_change(db, project_id, "preparation", i.id, "create", user.id, f"添加准备项「{i.name}」")
    db.commit()
    db.refresh(i)
    return _item_dict(db, i)


@router.put("/projects/{project_id}/procurements/{item_id}")
@route_permission('project.manage_plan')
def update_item(project_id: str, item_id: str, data: PrepItemUpdate,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _writable_preparation_project(db, project_id, user)
    i = db.get(ProjectPreparationItem, item_id, populate_existing=True)
    if i is None or i.project_id != project_id or i.category != "procurement":
        raise HTTPException(status_code=404, detail="准备项不存在")
    old = _item_dict(db, i)
    previous_status = i.status
    if "owner_id" in data.model_fields_set and data.owner_id != i.owner_id:
        _validate_owner(db, data.owner_id)
    old_extra = i.extra or {}
    next_extra = {**old_extra, **data.extra} if data.extra is not None else old_extra
    material_change = any(old_extra.get(key) != next_extra.get(key)
                          for key in ("quantity", "spec", "unit"))
    for f, v in data.model_dump(exclude_unset=True).items():
        if f == "extra":
            if v is not None:
                i.extra = next_extra
        elif v is not None or f in ("owner_id", "required_date", "committed_date", "forecast_date", "actual_date"):
            setattr(i, f, v)
    if material_change:
        # 数量、规格或单位变了必须重新核对；同次表单回传的旧完成状态不沿用。
        if i.status in ("passed", "na"):
            i.status = "pending"
            i.actual_date = None
            i.completed_by = None
            i.completed_at = None
    _record_preparation_completion(i, p, user, previous_status)
    db.flush()
    if material_change:
        from app.services.notify import notify
        manager = db.get(User, p.manager) if p.manager else None
        if manager and manager.id != user.id:
            notify(db, manager.id, f'「{p.name}」采购需求发生变化',
                '采购数量、规格或单位已变化，请重新核对采购项。', ntype='system', project_id=project_id)
    log_change(db, project_id, "preparation", i.id, "update", user.id,
               f"更新准备项「{i.name}」（{STATUS_LABEL.get(i.status, i.status)}）" +
               ("；需求数量/规格/单位变化，请重新核对采购" if material_change else ""), old, _item_dict(db, i))
    db.commit()
    db.refresh(i)
    return _item_dict(db, i)


@router.delete("/projects/{project_id}/procurements/{item_id}")
@route_permission('project.manage_plan')
def delete_item(project_id: str, item_id: str,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _writable_preparation_project(db, project_id, user)
    i = db.get(ProjectPreparationItem, item_id, populate_existing=True)
    if i is None or i.project_id != project_id or i.category != "procurement":
        raise HTTPException(status_code=404, detail="准备项不存在")
    name = i.name
    db.delete(i)
    db.flush()
    log_change(db, project_id, "preparation", item_id, "delete", user.id, f"删除准备项「{name}」")
    db.commit()
    return {"message": "已删除"}


