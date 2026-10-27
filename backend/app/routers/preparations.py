"""Project preparation routes: 项目准备（进场前就绪判断）。

四分类：scope 范围与资料 / procurement 项目采购 / vehicle 车辆 / software 软件 / site 进场条件。
写操作权限 = project.manage_plan（项目管理人员）；读 = 项目可见。
所有修改 log_change() 审计；附件复用 attachments（entity_type=preparation_item）。
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
from app.models import Project, ProjectPreparationItem, User, Module
from app.services.scope import ensure_project_visible
from app.services.permissions import authorize_project, C_PLAN
from app.services.project_lifecycle import ensure_project_writable
from app.services.change_log import log_change
from app.services.project_events import planned_event_date

router = APIRouter(tags=["准备"])

CATEGORY_LABEL = {
    "scope": "范围与资料",
    "procurement": "项目采购",
    "vehicle": "车辆",
    "software": "软件",
    "site": "进场条件",
}
STATUS_LABEL = {
    "not_started": "未开始", "in_progress": "进行中", "pending": "待确认",
    "passed": "已通过", "failed": "不通过", "na": "不适用",
}
STATUS_COLOR = {
    "not_started": "default", "in_progress": "blue", "pending": "orange",
    "passed": "green", "failed": "red", "na": "default",
}
PARTY_LABEL = {
    "project": "项目团队", "client": "客户", "procurement": "采购部门",
    "production": "生产部门", "software": "软件团队", "company": "项目团队",
}

# 默认准备清单（创建项目时自动生成；PM 可增删）
DEFAULT_ITEMS = [
    ("scope", "项目实施范围冻结", True, True, "project", "low"),
    ("scope", "现场布局图", True, False, "client", "medium"),
    ("scope", "点位表", True, True, "client", "high"),
    ("scope", "客户系统接口文档（WMS/MES）", False, False, "client", "medium"),
    ("scope", "验收标准确认", True, False, "client", "low"),
    ("vehicle", "车辆交付", True, True, "production", "high"),
    ("software", "调度系统项目配置", True, False, "software", "high"),
    ("site", "现场施工完成", True, True, "client", "high"),
    ("site", "网络检查", True, True, "client", "high"),
    ("site", "实施人员安排", True, False, "project", "medium"),
    ("site", "入场手续", True, True, "project", "medium"),
]

# 按条件生成的附加清单（新建项目选项）
CONDITION_ITEMS = {
    "need_wms": [
        ("scope", "接口协议确认", True, True, "client", "high"),
        ("scope", "测试环境提供", True, False, "client", "high"),
        ("scope", "测试账号提供", False, False, "client", "medium"),
        ("site", "网络连通检查", True, True, "client", "high"),
        ("software", "联调计划确认", True, False, "software", "medium"),
    ],
    "need_charging": [
        ("procurement", "充电设备交付", True, True, "procurement", "high"),
        ("site", "充电区域施工", True, True, "client", "high"),
        ("site", "电源条件确认", True, False, "client", "medium"),
        ("software", "充电通讯测试条件", False, False, "software", "low"),
    ],
    "client_server": [
        ("scope", "服务器配置确认", True, False, "client", "high"),
        ("scope", "操作系统准备", True, False, "client", "medium"),
        ("site", "网络端口开放", True, True, "client", "high"),
        ("scope", "远程访问方式确认", False, False, "client", "low"),
    ],
    "new_vehicles": [
        ("vehicle", "设计冻结", True, False, "production", "medium"),
        ("vehicle", "首车完成", True, False, "production", "high"),
        ("vehicle", "厂内测试通过", True, True, "production", "high"),
        ("vehicle", "发货", True, True, "production", "high"),
        ("vehicle", "到场确认", True, True, "production", "high"),
    ],
    "overseas": [
        ("scope", "发运和清关计划", True, True, "project", "high"),
        ("site", "人员签证/邀请函", True, True, "project", "high"),
        ("site", "入场手续（海外）", True, False, "client", "medium"),
        ("site", "当地网络和通信条件", True, False, "client", "medium"),
        ("site", "现场交通住宿安排", False, False, "project", "low"),
    ],
}


class PrepItemCreate(BaseModel):
    category: str = Field(default="procurement", pattern="^(scope|procurement|vehicle|software|site)$")
    name: str = Field(..., min_length=1, max_length=200)
    is_required: bool = False
    blocks_entry: bool = False
    status: str = Field(default="not_started",
                        pattern="^(not_started|in_progress|pending|passed|failed|na)$")
    owner_id: Optional[str] = None  # 内部跟进人
    owner_party: str = Field(default="project",
                             pattern="^(project|client|procurement|production|software|company)$")
    required_date: Optional[date] = None  # 项目要求日期
    committed_date: Optional[date] = None  # 责任方承诺日期
    forecast_date: Optional[date] = None  # 当前预计日期
    planned_date: Optional[date] = None  # 兼容旧数据
    actual_date: Optional[date] = None
    risk: str = Field(default="low", pattern="^(low|medium|high)$")
    affected_phase_id: Optional[str] = None
    affected_task_id: Optional[str] = None
    note: str = ""
    extra: Optional[dict] = None


class PrepItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    is_required: Optional[bool] = None
    blocks_entry: Optional[bool] = None
    status: Optional[str] = Field(default=None,
                                  pattern="^(not_started|in_progress|pending|passed|failed|na)$")
    owner_id: Optional[str] = None
    owner_party: Optional[str] = Field(default=None, pattern="^(project|client|procurement|production|software|company)$")
    required_date: Optional[date] = None
    committed_date: Optional[date] = None
    forecast_date: Optional[date] = None
    planned_date: Optional[date] = None
    actual_date: Optional[date] = None
    risk: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")
    affected_phase_id: Optional[str] = None
    affected_task_id: Optional[str] = None
    note: Optional[str] = None
    extra: Optional[dict] = None


def _writable_preparation_project(db: Session, project_id: str, user: User) -> Project:
    """Serialize requirements and their review decision against the same project."""
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
    # Legacy future dates remain visible for correction, without claiming readiness.
    return item.status == "passed" and (item.actual_date is None or item.actual_date <= today)


def _validate_owner(db: Session, owner_id: Optional[str]) -> None:
    if owner_id:
        person = db.get(User, owner_id)
        if person is None or not person.is_active:
            raise HTTPException(status_code=400, detail="内部跟进人必须是启用的系统用户")


def _project_phase(db: Session, project_id: str, phase_id: Optional[str]):
    from app.models import Phase
    phase = db.get(Phase, phase_id) if phase_id else None
    # Old projects may still reference a shared template phase through their modules.
    if phase and (phase.project_id == project_id or (
        phase.project_id is None and db.query(Module.id).filter_by(
            project_id=project_id, phase_id=phase_id).first())):
        return phase
    return None


def _validate_impact_links(db: Session, project_id: str, data) -> None:
    from app.models import Task
    if data.affected_task_id:
        task = db.get(Task, data.affected_task_id)
        if task is None or task.project_id != project_id:
            raise HTTPException(400, "影响任务不存在或不属于当前项目")
    if data.affected_phase_id and not _project_phase(db, project_id, data.affected_phase_id):
        raise HTTPException(400, "影响阶段不存在或不属于当前项目")


def _item_dict(db: Session, i: ProjectPreparationItem) -> dict:
    owner = db.get(User, i.owner_id) if i.owner_id else None
    from app.models import Task as _T
    task = db.get(_T, i.task_id) if i.task_id else None
    a_task = db.get(_T, i.affected_task_id) if i.affected_task_id else None
    a_phase = _project_phase(db, i.project_id, i.affected_phase_id)
    # Do not expose names from malformed legacy links to another project.
    task = task if task and task.project_id == i.project_id else None
    a_task = a_task if a_task and a_task.project_id == i.project_id else None
    return {
        "id": i.id,
        "category": i.category,
        "name": i.name,
        "task_id": i.task_id,
        "task_name": task.name if task else "",
        "is_required": i.is_required,
        "blocks_entry": i.blocks_entry,
        "status": i.status,
        "owner_id": i.owner_id,
        "owner_name": owner.display_name if owner else "",
        "owner_party": i.owner_party,
        "required_date": i.required_date.isoformat() if i.required_date else (i.planned_date.isoformat() if i.planned_date else None),
        "committed_date": i.committed_date.isoformat() if i.committed_date else None,
        "forecast_date": i.forecast_date.isoformat() if i.forecast_date else None,
        "planned_date": i.planned_date.isoformat() if i.planned_date else None,
        "actual_date": i.actual_date.isoformat() if i.actual_date else None,
        "risk": i.risk,
        "affected_phase_id": i.affected_phase_id,
        "affected_phase_name": a_phase.name if a_phase else "",
        "affected_task_id": i.affected_task_id,
        "affected_task_name": a_task.name if a_task else "",
        "completed_by": i.completed_by,
        "completed_at": i.completed_at.isoformat() if i.completed_at else None,
        "note": i.note,
        "extra": i.extra or {},
        "sort_order": i.sort_order,
    }


def _summary(db: Session, project: Project) -> dict:
    """Compatibility read model; dispatch readiness comes only from stage-five documents."""
    from app.services.dispatch_review import summary
    return summary(db, project)


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
        'overdue': sum(bool(row.required_date or row.planned_date) and (row.required_date or row.planned_date) < today for row in pending),
        'planned_ship_date': ship.isoformat() if ship else None,
        'dispatch_readiness': _summary(db, project)}


def seed_default_preparations(db: Session, project_id: str, conditions=None, planned_entry_date=None) -> int:
    """T22: document definitions replace non-procurement preparation generation."""
    return 0


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
            blocks_entry=False,
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


def _infer_category(name: str) -> str:
    """按名称推断准备项分类（模板阶段任务自动成为准备项时用）。"""
    n = name
    if any(k in n for k in ("布局", "点位", "接口文档", "范围", "验收标准", "方案确认", "勘测")):
        return "scope"
    if any(k in n for k in ("车辆", "发货")):
        return "vehicle"
    if any(k in n for k in ("调度", "软件", "接口程序", "参数包")):
        return "software"
    if any(k in n for k in ("网络", "施工", "入场", "人员", "充电", "围栏", "安全")):
        return "site"
    if any(k in n for k in ("采购", "充电桩", "工控机", "物料")):
        return "procurement"
    return "scope"


def sync_preparation_items(db: Session, project_id: str) -> int:
    """T22: document definitions replace non-procurement preparation generation."""
    return 0


@router.get("/projects/{project_id}/procurements")
@route_permission('project.read')
def list_preparations(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """准备清单 + 状态摘要（项目可见即可读）。"""
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
    if data.category != "procurement":
        raise HTTPException(400, "非采购准备事项已并入资料要求")
    _validate_owner(db, data.owner_id)
    _validate_impact_links(db, project_id, data)
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
    _validate_impact_links(db, project_id, data)
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
        elif v is not None or f in ("owner_id", "required_date", "committed_date", "forecast_date", "planned_date", "actual_date", "affected_phase_id", "affected_task_id"):
            setattr(i, f, v)
    if material_change:
        # 旧评审/审计保留原数量、规格和完成信息。新需求必须重新核对，
        # 同次表单回传旧 passed/na 状态也不能沿用原确认。
        if i.status in ("passed", "na"):
            i.status = "pending"
            i.actual_date = None
            i.completed_by = None
            i.completed_at = None
    _record_preparation_completion(i, p, user, previous_status)
    db.flush()
    if material_change:
        from app.routers.notifications import notify
        manager = db.get(User, p.manager) if p.manager else None
        if manager and manager.id != user.id:
            notify(db, manager.id, f'「{p.name}」采购需求发生变化',
                '采购数量、规格或单位已变化，请重新核对采购项；发车前资料按第5阶段资料单独核验。', ntype='system', project_id=project_id)
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
    p = _writable_preparation_project(db, project_id, user)
    i = db.get(ProjectPreparationItem, item_id, populate_existing=True)
    if i is None or i.project_id != project_id or i.category != "procurement":
        raise HTTPException(status_code=404, detail="准备项不存在")
    name = i.name
    db.delete(i)
    db.flush()
    log_change(db, project_id, "preparation", item_id, "delete", user.id, f"删除准备项「{name}」")
    db.commit()
    return {"message": "已删除"}




class ConfirmReadyBody(BaseModel):
    conclusion: Optional[str] = Field(default="", max_length=4000)
    risk_entry: bool = False


@router.post("/projects/{project_id}/preparations/confirm-ready")
@route_permission('project.manage_plan')
def confirm_ready(project_id: str, data: ConfirmReadyBody = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    raise HTTPException(410, '旧准备评审入口已下线，请到资料清单进行发车前资料确认')

def _review_manifest(db: Session, project: Project) -> dict:
    from app.services.dispatch_review import manifest
    return manifest(db, project)


@router.post("/projects/{project_id}/preparations/review")
@route_permission('project.manage_plan')
def review_manifest(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    raise HTTPException(410, '旧准备评审入口已下线，请到资料清单进行发车前资料确认')


class ReviewConfirmBody(BaseModel):
    conclusion: str = Field(..., pattern="^(not_ready|risky|ready)$")
    notes: str = Field(default="", max_length=4000)
    review_token: Optional[str] = Field(default=None, max_length=64)
    remaining_risks: Optional[list] = None  # [{name, owner, due, plan}]


@router.post("/projects/{project_id}/preparations/review/confirm")
@route_permission('project.manage_plan')
def review_confirm(project_id: str, data: ReviewConfirmBody,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    raise HTTPException(410, '旧准备评审入口已下线，请到资料清单进行发车前资料确认')


@router.get("/projects/{project_id}/preparations/reviews")
@route_permission('project.read')
def list_reviews(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    raise HTTPException(410, '旧准备评审入口已下线，请到资料清单进行发车前资料确认')
