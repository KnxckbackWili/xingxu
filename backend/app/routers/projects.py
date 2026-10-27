from typing import Literal, Optional, Annotated

"""Project CRUD routes + vehicles + members."""

from datetime import date
from app.services.system_permissions import route_permission, route_permission_contextual, route_permission_exempt
from app.time_utils import utcnow
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_pm
from app.services.permissions import require_project_capability
from app.services.scope import visible_project_ids, ensure_project_visible
from app.models import (
    User,
    Project,
    Vehicle,
    Phase,
    Module,
    ProjectMember,
    AcceptanceRecord,
)
from app.services.change_log import log_change
from app.services.system_permissions import has_permission
from app.services.project_lifecycle import (
    INITIAL_PROJECT_STATUSES,
    PROJECT_STATUSES,
    SUSPENDABLE_PROJECT_STATUSES,
    can_transition,
    status_label,
)

from app.services.project_events import (
    DispatchPlatform, EventPlanInput, events_for_project, planned_event_date, update_plans, sync_arrival_all,
)

def _private_response(response:Response):
    response.headers["Cache-Control"]="private, no-store"


router = APIRouter(prefix="/projects", tags=["项目"],dependencies=[Depends(_private_response)])


class VehicleCreate(BaseModel):
    model_config = {"protected_namespaces": ()}

    vehicle_type: str = Field(..., min_length=1, max_length=50)
    model_name: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(..., gt=0)
    configuration: dict = Field(default_factory=dict)
    notes: str = Field(default="", max_length=2000)
    sort_order: int = 0


class ProjectCreate(EventPlanInput):
    name: str = Field(..., min_length=1, max_length=200)
    abbreviation: str = ""
    client: str = ""
    location: str = ""
    timezone: str = Field(
        default="Asia/Shanghai", max_length=64
    )  # 项目现场时区（IANA）
    start_date: date
    end_date: date
    status: str = Field(default="preparing", max_length=20)
    description: str = ""
    manager_id: Optional[str] = None
    technical_manager_id: Optional[str] = None
    dispatch_platform: DispatchPlatform | None = None
    # 实施准备从 module_ids 自动推导；need_* 保留给旧客户端显式补充。
    need_wms: bool = False
    need_charging: bool = False
    client_server: bool = False
    new_vehicles: bool = True  # AGV 项目默认新造车辆
    overseas: bool = False

    # 可选，兼容只创建项目的旧客户端；创建向导一次提交完整配置。
    vehicles: list[VehicleCreate] = Field(default_factory=list, max_length=100)
    module_ids: Optional[list[str]] = Field(default=None, max_length=500)  # legacy source adapter
    work_item_ids: Optional[list[str]] = Field(default=None, max_length=2000)
    template_id: str = Field(default="default", min_length=1, max_length=100)
    task_quantities: dict[str, Annotated[float, Field(gt=0, allow_inf_nan=False)]] = (
        Field(default_factory=dict)
    )
    exclude_task_ids: list[str] = Field(default_factory=list, max_length=2000)
    client_uuid: Optional[str] = Field(default=None, min_length=8, max_length=64)


class ClientContact(BaseModel):
    model_config = {"extra": "forbid"}

    department: str = Field(default="", max_length=100)
    team: str = Field(default="", max_length=100)
    name: str = Field(..., min_length=1, max_length=100)
    title: str = Field(default="", max_length=100)
    phone: str = Field(default="", max_length=50)
    email: str = Field(default="", max_length=200)
    responsibility: str = Field(default="", max_length=500)
    decision_scope: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=1000)
    is_primary: bool = False


class EntryPlan(BaseModel):
    model_config = {"extra": "forbid"}

    mode: str = Field(
        default="",
        pattern="^(|collective|staggered|self_arranged|client_pickup|resident|other)$",
    )
    meeting_time: str = Field(default="", max_length=50)
    meeting_point: str = Field(default="", max_length=300)
    client_contact: str = Field(default="", max_length=100)
    contact_phone: str = Field(default="", max_length=50)
    transport: str = Field(default="", max_length=300)
    accommodation: str = Field(default="", max_length=300)
    access_requirements: str = Field(default="", max_length=2000)
    tools_ppe: str = Field(default="", max_length=2000)
    network_access: str = Field(default="", max_length=2000)
    vehicle_access: str = Field(default="", max_length=500)
    safety_requirements: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=3000)


class CoManagerGrant(BaseModel):
    model_config = {"extra": "forbid"}

    user_id: str
    expires_at: Optional[date] = None


class MemberPermissionGrant(BaseModel):
    model_config = {"extra": "forbid"}

    user_id: str
    capabilities: list[str] = Field(max_length=8)


class ProjectUpdate(EventPlanInput):
    @model_validator(mode="before")
    @classmethod
    def readonly_portable_source(cls,value):
        if isinstance(value,dict) and 'portable_unverified_snapshot' in value:
            raise ValueError('便携导入执行来源为只读，不能通过项目修改接口覆写')
        return value

    name: Optional[str] = None
    abbreviation: Optional[str] = None
    client: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = Field(default=None, max_length=64)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    description: Optional[str] = None
    staffing_notes: Optional[str] = Field(default=None, max_length=5000)
    manager_id: Optional[str] = None
    technical_manager_id: Optional[str] = None
    dispatch_platform: DispatchPlatform | None = None
    members: Optional[list[str]] = None
    member_removal_confirmations: list[str]|None = Field(default=None,max_length=500)
    member_permissions: Optional[list[MemberPermissionGrant]] = Field(
        default=None, max_length=500
    )
    rest_mode: Optional[str] = Field(default=None, pattern="^(none|one|two)$")
    rest_days: Optional[list[str]] = None
    skip_holidays: Optional[bool] = None
    client_contacts: Optional[list[ClientContact]] = None
    entry_plan: Optional[EntryPlan] = None
    co_managers: Optional[list[CoManagerGrant]] = None
    version: Optional[int] = None  # 乐观锁版本号


class VehicleUpdate(BaseModel):
    model_config = {"protected_namespaces": ()}

    vehicle_type: Optional[str] = None
    model_name: Optional[str] = None
    quantity: Optional[int] = Field(default=None, gt=0)
    configuration: Optional[dict] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    sort_order: Optional[int] = None


def _vehicle_dict(v: Vehicle) -> dict:
    return {
        "id": v.id,
        "vehicle_type": v.vehicle_type,
        "model_name": v.model_name,
        "quantity": v.quantity,
        "configuration": v.configuration or {},
        "notes": v.notes or "",
        "sort_order": v.sort_order,
    }


def _valid_timezone(tz: str) -> str:
    """校验 IANA 时区名；非法值 → 400（防脏数据进入 timezone 列）。"""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=400, detail=f"无效的时区：{tz}")
    return tz


def _project_dict(db: Session, p: Project, event_rows=None) -> dict:
    _mgr = db.get(User, p.manager) if p.manager else None
    from app.services.scope import active_co_manager

    co_managers = []
    for grant in p.co_managers or []:
        person = db.get(User, grant.get("user_id")) if grant.get("user_id") else None
        co_managers.append(
            {
                **grant,
                "display_name": person.display_name if person else "",
                "role": person.role if person else "",
                "is_active": active_co_manager(p, grant.get("user_id", "")),
            }
        )
    suspension = dict(p.suspension or {})
    if suspension:
        for key in ("suspended_by", "resumed_by"):
            if suspension.get(key):
                person = db.get(User, suspension[key])
                suspension[f"{key}_name"] = person.display_name if person else ""
    return {
        "id": p.id,
        "name": p.name,
        "abbreviation": p.abbreviation,
        "manager": p.manager,
        "manager_name": _mgr.display_name if _mgr else "",
        "technical_manager": p.technical_manager,
        "technical_manager_name": (
            db.get(User, p.technical_manager).display_name
            if p.technical_manager and db.get(User, p.technical_manager)
            else ""
        ),
        "co_managers": co_managers,
        "client": p.client,
        "location": p.location,
        "timezone": p.timezone or "Asia/Shanghai",
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "status": p.status,
        "legacy_lifecycle": p.legacy_lifecycle,
        "suspension": suspension,
        "description": p.description,
        "staffing_notes": p.staffing_notes or "",
        "members": p.members or [],
        "member_permissions": p.member_permissions or [],
        "rest_mode": p.rest_mode or "none",
        "rest_days": p.rest_days or [],
        "skip_holidays": bool(p.skip_holidays),
        "schedule_version": p.schedule_version or 0,
        "version": p.version or 0,
        "planned_entry_date": (
            p.planned_entry_date.isoformat() if p.planned_entry_date else None
        ),
        "prep_confirmed_by": p.prep_confirmed_by,
        "prep_confirmed_at": (
            p.prep_confirmed_at.isoformat() if p.prep_confirmed_at else None
        ),
        "prep_conclusion": p.prep_conclusion or "",
        "client_contacts": p.client_contacts or [],
        "entry_plan": p.entry_plan or {},
        "dispatch_platform": p.dispatch_platform,
        "events": events_for_project(db, p, event_rows),
        **_holiday_calendar(db, p),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _holiday_calendar(db: Session, p: Project) -> dict:
    """Unknown years are explicit; yearly maintenance is visible immediately."""
    from app.services.holidays import calendar_in_range
    return calendar_in_range(p.start_date, p.end_date, db)


def get_project_or_404(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return p


# ===== Projects =====


@router.get("")
@route_permission('project.read')
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=200),
    search: str = Query("", max_length=100),
    status: str = Query("", max_length=30),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List projects filtered by role scope and explicit project assignment.

    默认保持旧行为返回完整 list；当 page/page_size > 0 时返回服务端分页结构，
    避免 500 个项目时一次拉回全部数据。
    """
    from app.services.scope import visible_projects

    projects = visible_projects(db, user)

    query = search.strip().lower()
    if query:
        projects = [
            p
            for p in projects
            if query in (p.name or "").lower()
            or query in (p.client or "").lower()
            or query in (p.abbreviation or "").lower()
            or query in (p.location or "").lower()
        ]
    if status:
        projects = [p for p in projects if p.status == status]

    projects.sort(key=lambda p: p.created_at or p.id, reverse=True)
    from app.services.scope import active_co_manager

    from app.models import ProjectEvent
    event_projects = projects[(page - 1) * page_size:page * page_size] if page_size else projects
    events_by_project = {project.id: [] for project in event_projects}
    if events_by_project:
        for event in db.query(ProjectEvent).filter(ProjectEvent.project_id.in_(events_by_project)).all():
            events_by_project[event.project_id].append(event)

    from app.services.workbench import project_facts
    facts=project_facts(db,event_projects,user)

    def serialize(project):
        item = _project_dict(db, project, events_by_project.get(project.id, []))
        item["is_co_manager"] = active_co_manager(project, user.id)
        from app.services.permissions import (
            project_capabilities,
            grantable_project_capabilities,
        )

        item["grantable_capabilities"] = sorted(
            grantable_project_capabilities(user, project)
        )
        item["capabilities"] = sorted(project_capabilities(user, project))
        item["can_delete"] = "project.delete" in item["capabilities"]
        item.update(facts[project.id])
        return item

    if page_size > 0:
        total = len(projects)
        start = (page - 1) * page_size
        items = [serialize(p) for p in projects[start : start + page_size]]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    return [serialize(p) for p in projects]


def _sync_project_members(db: Session, project: Project):
    """把项目 JSON members/manager/technical/co_managers 同步到 project_members 表。"""
    project.member_permissions = [
        grant
        for grant in project.member_permissions or []
        if grant.get("user_id") in (project.members or [])
    ]
    rows = db.query(ProjectMember).filter(ProjectMember.project_id == project.id).all()
    existing = {row.user_id: row for row in rows}
    to_add = set(project.members or [])
    if project.manager:
        to_add.add(project.manager)
    if project.technical_manager:
        to_add.add(project.technical_manager)
    for grant in project.co_managers or []:
        if grant.get("user_id"):
            to_add.add(grant["user_id"])
    for uid, row in existing.items():
        if uid not in to_add:
            db.delete(row)
    for uid in to_add:
        if uid and uid not in existing:
            db.add(ProjectMember(project_id=project.id, user_id=uid, role="member"))
    db.flush()


def _validate_user_ids(db: Session, ids, label="成员"):
    """校验用户 ID 存在且启用：坏 ID 返回 400 + 字段级提示，而不是 FK 500（D2/C1-2/C3-4）。"""
    if not ids:
        return
    bad = []
    for uid in dict.fromkeys(ids):
        if not uid:
            continue
        u = db.get(User, uid)
        if u is None:
            bad.append(f"不存在的用户 {uid[:8]}")
        elif not u.is_active:
            bad.append(f"已停用用户 {u.display_name or uid[:8]}")
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"{label}校验失败："
            + "、".join(bad[:5])
            + (" 等" if len(bad) > 5 else ""),
        )


@router.post("", response_model=dict)
@route_permission('projects.create')
def create_project(
    data: ProjectCreate,
    user: User = Depends(require_pm),
    db: Session = Depends(get_db),
):
    from hashlib import sha256
    import json
    from sqlalchemy.exc import IntegrityError
    from app.models import ProjectCreationReceipt

    fingerprint = sha256(
        json.dumps(
            data.model_dump(mode="json", exclude={"client_uuid"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    def replay():
        receipt = (
            db.query(ProjectCreationReceipt)
            .filter_by(user_id=user.id, client_uuid=data.client_uuid)
            .first()
        )
        if receipt is None:
            return None
        if receipt.request_hash != fingerprint:
            raise HTTPException(
                409,
                "该创建请求已成功，但本次内容与原请求不同；请到项目列表查看已创建项目",
            )
        ensure_project_visible(db, receipt.project_id, user)
        return receipt.result

    if data.client_uuid:
        previous = replay()
        if previous is not None:
            return previous
    copied_files = []
    db.info["creation_copied_files"] = copied_files
    try:
        result = _create_project(data, user, db)
        if data.client_uuid:
            db.add(
                ProjectCreationReceipt(
                    user_id=user.id,
                    client_uuid=data.client_uuid,
                    request_hash=fingerprint,
                    project_id=result["id"],
                    result=result,
                )
            )
        db.commit()
    except Exception as error:
        db.rollback()
        for path in copied_files:
            path.unlink(missing_ok=True)
        if isinstance(error, IntegrityError) and data.client_uuid:
            previous = replay()
            if previous is not None:
                return previous
        raise
    finally:
        db.info.pop("creation_copied_files", None)
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return result


def _create_project(data: ProjectCreate, user: User, db: Session):
    if not data.name.strip():
        raise HTTPException(400, "项目名称不能为空")
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    if data.status not in INITIAL_PROJECT_STATUSES:
        allowed = "、".join(status_label(value) for value in INITIAL_PROJECT_STATUSES)
        raise HTTPException(status_code=400, detail=f"新项目状态只能选择：{allowed}")
    # 成员 ID 合法性：坏 ID 在 SQLAlchemy 层会炸 FK 500，这里提前 400（C1-2/D2）
    if data.manager_id:
        _validate_user_ids(db, [data.manager_id], label="项目经理")
    if data.technical_manager_id:
        _validate_user_ids(db, [data.technical_manager_id], label="技术负责人")
    members = []
    if data.manager_id:
        members.append(data.manager_id)
    if data.technical_manager_id:
        technical = db.get(User, data.technical_manager_id)
        if technical is None or technical.role not in (
            "lead",
            "technician",
            "pm",
            "worker",
        ):
            raise HTTPException(
                status_code=400, detail="技术负责人必须是项目经理或实施工程师"
            )
        members.append(data.technical_manager_id)
    from app.models import Template

    template = (
        db.get(Template, data.template_id) if data.template_id != "default" else None
    )
    if data.template_id != "default" and template is None:
        raise HTTPException(400, "所选模板已不存在，请重新选择实施方案")
    p = Project(
        template_id=data.template_id,
        template_version=template.version or 1 if template else 1,
        name=data.name.strip(),
        abbreviation=data.abbreviation,
        manager=data.manager_id or user.id,
        technical_manager=data.technical_manager_id,
        client=data.client,
        location=data.location,
        timezone=_valid_timezone(data.timezone),
        start_date=data.start_date,
        end_date=data.end_date,
        description=data.description,
        status=data.status,
        members=members,
        created_by=user.id,
        dispatch_platform=data.dispatch_platform,
    )
    db.add(p)
    db.flush()
    _sync_project_members(db, p)
    from app.services.vehicle_progress import initialize_project
    initialize_project(db, p, data.template_id)
    update_plans(db, p, data.event_plans, user.id)
    # 创建即生成默认准备清单（准备 Tab；按条件选项增补）+ 保存条件供任务生成时同步
    from app.routers.preparations import seed_default_preparations

    conditions = {}
    for k in ("need_wms", "need_charging", "client_server", "new_vehicles", "overseas"):
        if getattr(data, k, False):
            conditions[k] = True
    from app.services.preparation_scope import conditions_for_scope

    try:
        for condition in conditions_for_scope(
            db, data.template_id, data.work_item_ids if data.work_item_ids is not None else data.module_ids or [], data.exclude_task_ids
        ):
            conditions[condition] = True
    except ValueError as error:
        raise HTTPException(400, str(error))
    p.prep_conditions = [k for k, v in conditions.items() if v]
    seed_default_preparations(db, p.id, conditions, planned_event_date(db, p.id))
    log_change(
        db,
        p.id,
        "project",
        p.id,
        "create",
        user.id,
        f"创建项目「{p.name}」",
        None,
        _project_dict(db, p),
    )
    from app.routers.vehicle_types import validate_vehicle_type_value

    for vehicle_data in data.vehicles:
        payload = vehicle_data.model_dump()
        payload["vehicle_type"] = validate_vehicle_type_value(
            db, payload["vehicle_type"], allow_legacy=(user.role == "admin")
        )
        vehicle = Vehicle(project_id=p.id, **payload)
        db.add(vehicle)
        db.flush()
        log_change(
            db,
            p.id,
            "vehicle",
            vehicle.id,
            "create",
            user.id,
            f"新增车型 {vehicle.vehicle_type} {vehicle.model_name}",
        )
    from app.services.project_documents import initialize
    initialize(db, p)
    result = _project_dict(db, p)
    if data.module_ids is not None or data.work_item_ids is not None:
        from app.services.generate_tasks import (
            generate_tasks_for_modules,
            selected_execution_module_ids,
        )

        try:
            from app.services.work_items import selected_template_work
            selected=selected_template_work(db,data.template_id,data.work_item_ids if data.work_item_ids is not None else data.module_ids or [],data.exclude_task_ids)
            execution_ids=[t.id for t in selected]
            generated = (
                generate_tasks_for_modules(
                    db,
                    p,
                    execution_ids,
                    data.template_id,
                    task_quantities=data.task_quantities,
                    exclude_task_ids=[],
                )
                if execution_ids
                else {"tasks": 0, "check_items": 0, "modules": []}
            )
            from app.routers.preparations import sync_preparation_items

            sync_preparation_items(db, p.id)
        except ValueError as error:
            raise HTTPException(400, str(error))
        db.flush()
        log_change(
            db,
            p.id,
            "task",
            p.id,
            "generate",
            user.id,
            f"生成实施任务：{generated['tasks']} 个任务，{generated['check_items']} 个检查项",
        )
        from app.models import Task

        generated["zero_target_tasks"] = (
            db.query(Task)
            .filter(
                Task.project_id == p.id,
                Task.quantity_type == "per_vehicle",
                Task.target_quantity == 0,
            )
            .count()
        )
        result["initial_generation"] = generated
    return result


@router.get("/{project_id}", response_model=dict)
@route_permission('project.read')
def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = ensure_project_visible(db, project_id, user)
    result = _project_dict(db, p)
    # Detail only: a retrospective can be long and is unnecessary on every
    # project-list row. Keep legacy sections and the original UTC timestamp.
    retrospective = (
        dict(p.retrospective)
        if isinstance(p.retrospective, dict)
        else ({"content": p.retrospective} if isinstance(p.retrospective, str) else {})
    )
    author_id = retrospective.get("author")
    author = (
        db.get(User, author_id) if isinstance(author_id, str) and author_id else None
    )
    retrospective["author_name"] = author.display_name if author else ""
    result["retrospective"] = retrospective
    from app.services.project_templates import project_template_info

    result["source_template"] = project_template_info(db, p)
    from app.services.scope import active_co_manager

    result["is_co_manager"] = active_co_manager(p, user.id)
    from app.services.permissions import (
        project_capabilities,
        grantable_project_capabilities,
    )

    result["grantable_capabilities"] = sorted(grantable_project_capabilities(user, p))
    result["capabilities"] = sorted(project_capabilities(user, p))
    result["can_delete"] = "project.delete" in result["capabilities"]
    # Include vehicles summary
    result["vehicles"] = [
        _vehicle_dict(v)
        for v in db.query(Vehicle)
        .filter_by(project_id=p.id)
        .order_by(Vehicle.sort_order)
        .all()
    ]
    result["vehicle_total"] = sum(
        v.quantity for v in db.query(Vehicle).filter_by(project_id=p.id).all()
    )
    from app.services.weekly_plans import project_summary
    result['weekly_plan_summary']=project_summary(db,p,user)
    from app.services.acceptance import acceptance_summary

    result["acceptance_summary"] = acceptance_summary(db, p.id)
    return result


@router.get("/{project_id}/people", response_model=list)
@route_permission('project.read')
def project_people(
    project_id: str,
    include_candidates: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Project-local people, with minimal directory candidates for member managers."""
    p = ensure_project_visible(db, project_id, user)
    from app.services.permissions import authorize_project, C_MEMBERS

    query = db.query(User)
    if include_candidates:
        authorize_project(user, p, C_MEMBERS)
        query = query.filter(User.is_active == True)
    else:
        ids = set(p.members or []) | {p.manager, p.technical_manager}
        ids.update((grant.get("user_id") for grant in p.co_managers or []))
        query = query.filter(User.id.in_([uid for uid in ids if uid]))
    from app.services.permissions import inherited_project_capabilities

    return [
        {
            "id": person.id,
            "display_name": person.display_name,
            "role": person.role,
            "inherited_capabilities": sorted(inherited_project_capabilities(person, p)),
        }
        for person in query.order_by(User.display_name).all()
    ]


@router.get('/{project_id}/members/removal-preview')
@route_permission('project.manage_members')
def preview_member_removal(project_id:str,removed_ids:list[str]=Query(default=[]),
    user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.permissions import authorize_project,C_MEMBERS
    from app.services.document_triggers import removal_preview
    project=ensure_project_visible(db,project_id,user)
    authorize_project(user,project,C_MEMBERS)
    if len(removed_ids)>500 or len(set(removed_ids))!=len(removed_ids) or not set(removed_ids)<=(set(project.members or [])):
        raise HTTPException(400,'待移出人员必须是当前项目中不重复的成员')
    return removal_preview(db,project,set(removed_ids))


class DirectTransfer(BaseModel):
    model_config={'extra':'forbid'}
    target_manager_id:str=Field(min_length=1,max_length=36)
    reason:str=Field(min_length=5,max_length=1000)
    version:int=Field(strict=True,ge=0)
    member_removal_confirmations:list[str]=Field(default_factory=list,max_length=500)

    @model_validator(mode='after')
    def exact_input(self):
        if len(self.reason.strip())<5:raise ValueError('请填写至少5个字的更换理由')
        if len(self.member_removal_confirmations)!=len(set(self.member_removal_confirmations)):raise ValueError('确认离场人员不能重复')
        return self


@router.get('/{project_id}/transfer-preview')
@route_permission('project.update','project.manage_members')
def transfer_preview(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services import project_transfer
    return project_transfer.preview(db,project_transfer.authorize(db,project_id,user),user)


@router.post('/{project_id}/transfer')
@route_permission('project.update','project.manage_members')
def direct_transfer(project_id:str,body:DirectTransfer,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services import project_transfer
    project=project_transfer.transfer(db,project_id,user,body)
    result=_project_dict(db,project)
    result['viewer_retains_access']=project.id in visible_project_ids(db,user)
    return result


@router.post('/{project_id}/governance-requests')
@router.get('/governance/requests')
@router.get('/governance/requests/{request_id}/member-removal-preview')
@router.post('/governance/requests/{request_id}/review')
@router.post('/governance/requests/{request_id}/withdraw')
@route_permission_exempt('申请审批流程已退役；仅认证后返回410，不读取或改写历史行')
def retired_governance(user:User=Depends(get_current_user)):
    raise HTTPException(410,'申请审批流程已退役，请在项目设置中直接更换负责人；历史记录由私有加密备份保全')


@router.put("/{project_id}", response_model=dict)
@route_permission_contextual('project.update', 'project.manage_members', reason='处理器按提交字段分别校验项目资料和成员权限')
def update_project(
    project_id: str,
    data: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = ensure_project_visible(db, project_id, user)
    if data.model_fields_set & {'rest_mode','rest_days','skip_holidays'}:
        raise HTTPException(400,'排期设置请通过周计划专用设置接口维护，不能绕过调度权限')
    from app.services.record_lock import lock_record

    lock_record(db, p, conflict_detail="项目正由另一操作更新，请刷新后重试")
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    p = ensure_project_visible(db, project_id, user)
    from app.services.project_lifecycle import ensure_project_writable

    ensure_project_writable(p)
    from app.services.permissions import authorize_project, C_MEMBERS, C_UPDATE

    field_keys = set(data.model_dump(exclude_unset=True).keys())-{'member_removal_confirmations'}
    from app.services.permissions import grantable_project_capabilities

    grantable = grantable_project_capabilities(user, p)
    if "member_permissions" in field_keys and (not grantable):
        raise HTTPException(
            status_code=403, detail="只有项目负责人或系统管理员可以设置成员操作权限"
        )
    if "co_managers" in field_keys and (
        not (user.role == "admin" or (user.role == "pm" and p.manager == user.id))
    ):
        raise HTTPException(
            status_code=403, detail="只有项目经理或系统管理员可以设置项目协管"
        )
    if "manager_id" in field_keys:
        raise HTTPException(status_code=400,detail="请使用项目设置的更换负责人入口，填写理由并核对版本与离场资料")
    if "technical_manager_id" in field_keys and (
        not (user.role == "admin" or (user.role == "pm" and p.manager == user.id))
    ):
        raise HTTPException(
            status_code=403, detail="只有项目经理或系统管理员可以指定技术负责人"
        )
    if not field_keys - {"version"}:
        raise HTTPException(400, "请提供需要修改的项目字段")
    if field_keys & {"members", "member_permissions"}:
        authorize_project(user, p, C_MEMBERS)
    if field_keys - {"members", "member_permissions", "version"}:
        authorize_project(user, p, C_UPDATE)
    from app.services.optimistic import bump_version

    bump_version(p, data.version, db=db)
    if data.members is not None:
        _validate_user_ids(db, data.members, label="成员")
    if data.technical_manager_id is not None:
        _validate_user_ids(db, [data.technical_manager_id], label="技术负责人")
    old = _project_dict(db, p)
    old_members = set(p.members or [])
    fields = [
        "name",
        "abbreviation",
        "client",
        "location",
        "timezone",
        "start_date",
        "end_date",
        "description",
        "staffing_notes",
    ]
    for f in fields:
        v = getattr(data, f)
        if v is not None:
            setattr(p, f, _valid_timezone(v) if f == "timezone" else v)
    if "technical_manager_id" in data.model_fields_set:
        if data.technical_manager_id is not None:
            technical = db.get(User, data.technical_manager_id)
            if technical is None or technical.role not in (
                "lead",
                "technician",
                "pm",
                "worker",
            ):
                raise HTTPException(
                    status_code=400, detail="技术负责人必须是项目经理或实施工程师"
                )
            p.members = list(set((p.members or []) + [data.technical_manager_id]))
        p.technical_manager = data.technical_manager_id
    if "dispatch_platform" in data.model_fields_set:
        p.dispatch_platform = data.dispatch_platform
    if "event_plans" in data.model_fields_set:
        update_plans(db, p, data.event_plans, user.id)
    if "timezone" in data.model_fields_set:
        sync_arrival_all(db, p, user.id, "现场时区调整后重新汇总到场日期")
    if "dispatch_platform" in data.model_fields_set:
        from app.services.project_documents import materialize_static
        materialize_static(db, p)
    from app.services.document_deadlines import refresh_project
    refresh_project(db,p,actor_id=user.id)
    if data.members is not None:
        p.members = data.members
    if data.rest_mode is not None:
        p.rest_mode = data.rest_mode
    if data.rest_days is not None:
        p.rest_days = data.rest_days
    if data.skip_holidays is not None:
        p.skip_holidays = data.skip_holidays
    if "client_contacts" in data.model_fields_set:
        contacts = data.client_contacts or []
        if len(contacts) > 100:
            raise HTTPException(status_code=400, detail="甲方联系人不能超过 100 人")
        if sum((1 for contact in contacts if contact.is_primary)) > 1:
            raise HTTPException(status_code=400, detail="甲方主联系人只能设置 1 人")
        p.client_contacts = [contact.model_dump() for contact in contacts]
    if "entry_plan" in data.model_fields_set:
        p.entry_plan = (
            {
                **(p.entry_plan or {}),
                **data.entry_plan.model_dump(mode="json", exclude_unset=True),
            }
            if data.entry_plan is not None
            else ({"entry_date": p.entry_plan["entry_date"]} if "entry_date" in (p.entry_plan or {}) else {})
        )
    if "co_managers" in data.model_fields_set:
        grants = data.co_managers or []
        if len(grants) > 5:
            raise HTTPException(status_code=400, detail="一个项目最多设置 5 名协管")
        seen = set()
        normalized = []
        for grant in grants:
            person = db.get(User, grant.user_id)
            if (
                person is None
                or not person.is_active
                or person.role not in ("pm", "technician", "worker")
            ):
                raise HTTPException(
                    status_code=400,
                    detail="协管必须是启用的项目经理、技术工程师或实施工程师",
                )
            if grant.user_id in seen or grant.user_id == p.manager:
                continue
            seen.add(grant.user_id)
            normalized.append(grant.model_dump(mode="json"))
        p.co_managers = normalized
        p.members = list(set((p.members or []) + list(seen)))
    if "member_permissions" in data.model_fields_set:
        grants = data.member_permissions or []
        _validate_user_ids(db, [grant.user_id for grant in grants], label="授权成员")
        seen = set()
        normalized = []
        for grant in grants:
            if grant.user_id not in (p.members or []):
                raise HTTPException(400, "只能为当前项目成员设置操作权限")
            target = db.get(User, grant.user_id)
            if target.role == "readonly" and set(grant.capabilities) - {"project.export"}:
                raise HTTPException(400, "只读预设不能授予项目写权限，请先在账号设置调整角色")
            if grant.user_id in seen:
                raise HTTPException(400, "成员操作权限不能重复设置")
            seen.add(grant.user_id)
            if set(grant.capabilities) - grantable:
                raise HTTPException(403, "不能授予非项目操作权限或超出自身范围的权限")
            if grant.capabilities:
                normalized.append(
                    {
                        "user_id": grant.user_id,
                        "capabilities": sorted(set(grant.capabilities)),
                    }
                )
        p.member_permissions = normalized
    if p.end_date < p.start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    db.flush()
    _sync_project_members(db, p)
    removed = old_members - set(p.members or [])
    from app.services.document_triggers import confirm_removals,member_events
    confirm_removals(db,p,removed,data.member_removal_confirmations)
    if removed:
        from app.services.member_handover import ensure_member_handover

        ensure_member_handover(db, p, removed)
        member_events(db,p,removed,user.id)
        from app.routers.notifications import notify

        for uid in removed:
            if uid == user.id:
                continue
            person = db.get(User, uid)
            if person and person.is_active:
                notify(
                    db,
                    uid,
                    f"你已被移出项目「{p.name}」",
                    f"操作人：{user.display_name}；若为误操作请联系项目负责人",
                    ntype="project_membership",
                    project_id=p.id,
                )
        # Original daily assignment identities are immutable historical sources.
        # Published weekly obligations were checked above; drafts are not auto-reassigned.
    log_change(
        db,
        p.id,
        "project",
        p.id,
        "update",
        user.id,
        f"更新项目「{p.name}」",
        old,
        _project_dict(db, p),
    )
    db.commit()
    db.refresh(p)
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return _project_dict(db, p)


@router.delete("/{project_id}")
@route_permission('project.delete')
def delete_project(
    project_id: str,
    version: Optional[int] = Query(default=None, ge=0),
    reason: str = Query(default="", max_length=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.project_deletion import delete_project as delete_with_backup

    return delete_with_backup(db, project_id, user, version=version, reason=reason)


def _status_change_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """状态流转校验：C_UPDATE（PM/管理员）或 C_ARCHIVE（总监治理）均可（C8-2）。"""
    from app.services.permissions import (
        project_capabilities,
        inherited_project_capabilities,
        C_UPDATE,
        C_ARCHIVE,
    )
    from app.services.system_permissions import permission_override

    p = ensure_project_visible(db, project_id, user)
    # Explicit archive grants manage the checklist only; retain existing director governance.
    inherited_governance = (
        C_ARCHIVE in inherited_project_capabilities(user, p)
        and permission_override(user, C_ARCHIVE) is not False
    )
    if C_UPDATE not in project_capabilities(user, p) and not inherited_governance:
        raise HTTPException(status_code=403, detail="没有权限执行此操作")
    return p


class LegacyLifecycleRepair(BaseModel):
    model_config = {'extra': 'forbid'}
    version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=5000)


@router.post('/{project_id}/lifecycle-repair')
@route_permission('project.update')
def repair_legacy_lifecycle(project_id: str, body: LegacyLifecycleRepair,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.record_lock import lock_record
    from app.services.optimistic import bump_version
    from app.services.permissions import authorize_project, C_UPDATE
    p = ensure_project_visible(db, project_id, user)
    lock_record(db, p, conflict_detail='历史状态正在核对，请刷新后重试')
    db.refresh(user)
    if user.role != 'admin' or not user.is_active:
        raise HTTPException(403, '仅系统管理员可核对无法识别的历史状态')
    p = ensure_project_visible(db, project_id, user)
    authorize_project(user, p, C_UPDATE)
    evidence = dict(p.legacy_lifecycle or {})
    if not evidence.get('requires_repair'):
        raise HTTPException(409, '该项目无需历史状态修复，请使用正常状态推进')
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, '必须说明核对依据与重置筹备的理由')
    bump_version(p, body.version, db=db)
    before = {'status': p.status, 'suspension': p.suspension, 'legacy_lifecycle': evidence}
    p.status = 'preparing'
    p.suspension = {}
    p.legacy_lifecycle = {**evidence, 'requires_repair': False, 'repaired_by': user.id,
                          'repaired_at': utcnow().isoformat(), 'repair_reason': reason}
    log_change(db, p.id, 'project', p.id, 'lifecycle_repair', user.id,
               '管理员根据原始记录明确重置为筹备；后续须逐阶段重新核对推进', before,
               {'status': p.status, 'legacy_lifecycle': p.legacy_lifecycle})
    db.commit()
    from app.services.cache import cache_clear
    cache_clear('dashboard:')
    return {'status': p.status, 'version': p.version, 'legacy_lifecycle': p.legacy_lifecycle}


@router.get("/{project_id}/completion-review")
@route_permission('project.read')
def read_completion_review(project_id: str, target: Literal['completed', 'archived'] = 'completed',
    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.lifecycle_gates import completion_review
    return completion_review(db, ensure_project_visible(db, project_id, user), target, actor=user)


class ProjectStatusChange(BaseModel):
    status: str = Field(..., min_length=1, max_length=20)
    reason: str = Field(default="", max_length=5000)
    retrospective: str = Field(default="", max_length=10000)
    confirm_warnings: Optional[bool] = None


@router.post("/{project_id}/status")
@route_permission_contextual('project.update', 'project.archive', reason='处理器按项目资料权限或既有治理资格及目标状态校验')
def change_status(
    project_id: str,
    body: ProjectStatusChange,
    user: User = Depends(get_current_user),
    p: Project = Depends(_status_change_project),
    db: Session = Depends(get_db),
):
    from app.services.system_permissions import permission_override
    from app.services.record_lock import lock_record

    lock_record(db, p, conflict_detail="项目状态正由另一操作更新，请刷新后重试")
    # Ownership, grants and lifecycle may have changed while waiting for the lock.
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    p = _status_change_project(project_id, user, db)
    if (
        body.status == "archived"
        and permission_override(user, "project.archive") is False
    ):
        raise HTTPException(403, "归档操作已被系统管理员禁止")
    # Invalidate project edits that read an active state before this transition.
    from app.services.optimistic import bump_version

    bump_version(p, p.version)
    new_status = body.status
    if new_status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效状态: {new_status}")
    old_status = p.status
    if (p.legacy_lifecycle or {}).get("requires_repair"):
        raise HTTPException(400, "历史状态尚未核对，请管理员根据原始记录明确重置筹备")
    suspension = p.suspension or {}

    # 突发停工（HYPE-71）：旁路状态，不参与 STATUS_FLOW 相邻流转。
    # 仅运行中状态可进入；必须填写停工原因；恢复只能回到停工前状态。
    if new_status == "suspended":
        if old_status not in SUSPENDABLE_PROJECT_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"当前状态「{status_label(old_status)}」不能进入突发停工（仅运行中状态可停工）",
            )
        reason = body.reason.strip()
        if not reason:
            raise HTTPException(status_code=400, detail="进入突发停工必须填写停工原因")
        p.suspension = {
            "status_before": old_status,
            "reason": reason,
            "suspended_by": user.id,
            "suspended_at": utcnow().isoformat(),
        }
    elif old_status == "suspended":
        expected = suspension.get("status_before")
        if not expected:
            raise HTTPException(status_code=400, detail="缺少停工前状态记录，无法恢复")
        if new_status != expected:
            raise HTTPException(
                status_code=400,
                detail=f"突发停工后只能恢复到原状态「{status_label(expected)}」",
            )
        p.suspension = {
            **suspension,
            "resumed_by": user.id,
            "resumed_at": utcnow().isoformat(),
        }
    elif not can_transition(old_status, new_status):
        raise HTTPException(
            status_code=400,
            detail=f"不允许从「{status_label(old_status)}」切换到「{status_label(new_status)}」",
        )
    from dataclasses import asdict
    from app.services.lifecycle_gates import check_transition
    retrospective = body.retrospective.strip()
    if new_status == "archived" and retrospective:
        p.retrospective = {"content": retrospective, "written_at": utcnow().isoformat(), "author": user.id}
    from app.services.project_documents import materialize_static, filter_blockers
    materialize_static(db,p,actor_id=user.id)
    blockers = filter_blockers(db,p,user,check_transition(db, p, new_status))
    if blockers:
        raise HTTPException(status_code=400, detail={
            "message": "；".join(blocker.message for blocker in blockers),
            "blockers": [asdict(blocker) for blocker in blockers],
        })
    # Every route into execution (including restart/backstep) uses the current
    # risk review. Legacy confirm_warnings is accepted in the schema, never authority.
    warnings = []
    if new_status == "executing":
        from app.routers.preparations import _summary

        summ = _summary(db, p)
        if summ["entry_unmet"] or summ["missing"]:
            warnings.append(f"已批准风险进场，仍有 {summ['entry_unmet']} 项进场条件未满足" if not summ["missing"] else "已批准风险进场，准备清单为空")
        if summ["overdue"]:
            warnings.append(f"{summ['overdue']} 项准备项已逾期")
    old_status = p.status
    p.status = new_status
    db.flush()
    materialize_static(db,p,actor_id=user.id)
    if new_status == "suspended":
        _action_detail = f"项目突发停工（原因：{p.suspension.get('reason', '')}）：{status_label(old_status)} → 突发停工"
    elif old_status == "suspended":
        _action_detail = f"项目恢复运行：突发停工 → {status_label(new_status)}"
    else:
        _action_detail = (
            f"项目状态: {status_label(old_status)} → {status_label(new_status)}"
        )
    log_change(db, p.id, "project", p.id, "update", user.id, _action_detail)
    db.commit()
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return {
        "message": f"状态已更新为「{status_label(new_status)}」",
        "status": new_status,
        "warnings": warnings,
        "requires_confirmation": False,
    }


# ===== Acceptance (验收签字记录 C7-2) =====


class AcceptanceCreate(BaseModel):
    accepted_by_name: str = Field(..., min_length=1, max_length=100)
    accepted_at: date
    conclusion: str = Field(
        default="accepted", pattern="^(accepted|conditionally_accepted|rejected)$"
    )
    notes: str = ""
    attachment_id: Optional[str] = None


@router.post("/{project_id}/acceptance", response_model=dict)
@route_permission('project.update')
def create_acceptance(
    project_id: str,
    data: AcceptanceCreate,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.update")),
    db: Session = Depends(get_db),
):
    """录入验收签字记录。conclusion=accepted 是 completed 的前置门禁（C7-2）。

    允许从 ready（待进场）之后的任意状态录入——提前录入客户签字属正常数据准备，
    真正的约束在 completed 门禁（进度 100% + 交付物齐备 + 验收记录）。
    """
    from app.services.record_lock import lock_writable_project
    from app.services.permissions import authorize_project, C_UPDATE

    p = lock_writable_project(db, p, user)
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    authorize_project(user, p, C_UPDATE)
    effective_status = (
        (p.suspension or {}).get("status_before")
        if p.status == "suspended"
        else p.status
    )
    if effective_status not in (
        "ready",
        "executing",
        "acceptance",
        "completed",
    ):
        raise HTTPException(
            status_code=400, detail="项目尚未进入待进场或后续阶段，不能录入验收记录"
        )
    from app.time_utils import project_today

    local_today = project_today(p.timezone)
    if data.accepted_at > local_today:
        raise HTTPException(
            status_code=400,
            detail=f"验收日期不能晚于项目当地今天（{local_today.isoformat()}）",
        )
    signer_name = data.accepted_by_name.strip()
    if not signer_name:
        raise HTTPException(status_code=400, detail="请填写验收签字人姓名")
    if data.attachment_id:
        from app.models import Attachment

        attachment = db.get(Attachment, data.attachment_id)
        if attachment is None or attachment.project_id != project_id:
            raise HTTPException(400, "验收附件不存在或不属于当前项目")
    if data.attachment_id:
        from app.services import project_documents as documents
        from app.models import ProjectDocument, DocumentVersion
        if not documents.can_read_file(user, p, attachment):
            raise HTTPException(403, "没有该验收附件的查看权限")
        documents.validate_file(attachment)
        signature = db.query(ProjectDocument).filter_by(project_id=project_id, code='7.1', scope='project').first()
        if signature is not None and documents.applicable(p, signature):
            latest = db.query(DocumentVersion).filter_by(project_document_id=signature.id).order_by(
                DocumentVersion.uploaded_at.desc().nullslast(), DocumentVersion.id.desc()).first()
            if signature.status != 'submitted' or latest is None or latest.attachment_id != attachment.id:
                documents.submit(db, p, [signature.id], attachment.id, user, '验收记录关联的项目验收单')
    from app.services.acceptance import (
        acceptance_scope_fingerprint,
        next_acceptance_recorded_at,
    )

    record = AcceptanceRecord(
        scope_fingerprint=acceptance_scope_fingerprint(db, project_id),
        created_at=next_acceptance_recorded_at(db, project_id),
        project_id=project_id,
        accepted_by=user.id,
        accepted_by_name=signer_name,
        accepted_at=data.accepted_at,
        conclusion=data.conclusion,
        notes=data.notes,
        attachment_id=data.attachment_id,
        created_by=user.id,
    )
    db.add(record)
    db.flush()
    log_change(
        db,
        project_id,
        "project",
        project_id,
        "acceptance",
        user.id,
        f"录入验收记录：{data.accepted_by_name} {data.conclusion}",
    )
    db.commit()
    db.refresh(record)
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return _acceptance_dict(db, record)


@router.get("/{project_id}/acceptance", response_model=list)
@route_permission('project.read')
def list_acceptance(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_project_visible(db, project_id, user)
    from app.services.acceptance import acceptance_evidence

    return acceptance_evidence(db, project_id)


def _acceptance_dict(db: Session, r: AcceptanceRecord) -> dict:
    from app.services.acceptance import acceptance_evidence

    return next(
        row for row in acceptance_evidence(db, r.project_id) if row["id"] == r.id
    )


# ===== Vehicles =====


@router.get("/{project_id}/vehicles", response_model=list)
@route_permission('project.read')
def list_vehicles(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_project_visible(db, project_id, user)
    return [
        _vehicle_dict(v)
        for v in db.query(Vehicle)
        .filter_by(project_id=project_id)
        .order_by(Vehicle.sort_order)
        .all()
    ]


@router.post("/{project_id}/vehicles", response_model=dict)
@route_permission('project.update')
def add_vehicle(
    project_id: str,
    data: VehicleCreate,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.update")),
    db: Session = Depends(get_db),
):
    from app.services.record_lock import lock_writable_project
    from app.services.permissions import authorize_project, C_UPDATE

    lock_writable_project(db, p, user)
    authorize_project(user, p, C_UPDATE)
    from app.services.project_lifecycle import ensure_schedule_writable

    ensure_schedule_writable(p)
    # HYPE-63：车型字典校验（普通用户只能写入启用车型；管理员例外）。
    from app.routers.vehicle_types import validate_vehicle_type_value

    payload = data.model_dump()
    payload["vehicle_type"] = validate_vehicle_type_value(
        db, data.vehicle_type, allow_legacy=(user.role == "admin")
    )
    v = Vehicle(project_id=project_id, **payload)
    db.add(v)
    db.flush()
    from app.services.generate_tasks import recompute_per_vehicle_targets

    recompute_per_vehicle_targets(db, project_id)
    sync_arrival_all(db, p, user.id, "车型配置变化后重新核对整批车辆")
    log_change(
        db,
        project_id,
        "vehicle",
        v.id,
        "create",
        user.id,
        f"添加车型 {payload['vehicle_type']} {data.model_name} ×{data.quantity}",
    )
    db.commit()
    db.refresh(v)
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return _vehicle_dict(v)


@router.put("/{project_id}/vehicles/{vehicle_id}", response_model=dict)
@route_permission('project.update')
def update_vehicle(
    project_id: str,
    vehicle_id: str,
    data: VehicleUpdate,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.update")),
    db: Session = Depends(get_db),
):
    from app.services.record_lock import lock_writable_project
    from app.services.permissions import authorize_project, C_UPDATE

    lock_writable_project(db, p, user)
    authorize_project(user, p, C_UPDATE)
    v = db.get(Vehicle, vehicle_id)
    if v is None or v.project_id != project_id:
        raise HTTPException(status_code=404, detail="车型不存在")
    # HYPE-63：车型字典校验 — 未变更时保留当前值（含已停用/字典外历史值），变更则须为启用项。
    from app.routers.vehicle_types import validate_vehicle_type_value

    payload = data.model_dump(exclude_none=True)
    if payload.get("vehicle_type") is not None:
        payload["vehicle_type"] = validate_vehicle_type_value(
            db,
            payload["vehicle_type"],
            current_value=v.vehicle_type,
            allow_legacy=(user.role == "admin"),
        )
    previous_type = v.vehicle_type
    quantity_inputs_changed = any(
        key in payload and payload[key] != getattr(v, key)
        for key in ("quantity", "vehicle_type")
    )
    if quantity_inputs_changed:
        from app.services.project_lifecycle import ensure_schedule_writable

        ensure_schedule_writable(p)
    for f, val in payload.items():
        setattr(v, f, val)
    db.flush()
    from app.services.generate_tasks import recompute_per_vehicle_targets

    if quantity_inputs_changed:
        recompute_per_vehicle_targets(db, project_id)
    if v.vehicle_type != previous_type:
        from app.models import VehicleUnit
        from app.services.vehicle_checks import reconcile_vehicle_type
        checks=reconcile_vehicle_type(db,project_id,db.query(VehicleUnit).filter_by(project_id=project_id,vehicle_id=v.id).all(),previous_type)
        if checks:
            log_change(db,project_id,"vehicle_check",v.id,"generate_scope",user.id,
                f"车型适用范围变化，为真实车辆新增{len(checks)}项待检检查",{"vehicle_type":previous_type},
                {"vehicle_type":v.vehicle_type,"check_ids":[c.id for c in checks]})
    sync_arrival_all(db, p, user.id, "车型配置变化后重新核对整批车辆")
    log_change(
        db,
        project_id,
        "vehicle",
        v.id,
        "update",
        user.id,
        f"更新车型 {v.vehicle_type} {v.model_name}",
    )
    db.commit()
    db.refresh(v)
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return _vehicle_dict(v)


@router.delete("/{project_id}/vehicles/{vehicle_id}")
@route_permission('project.update')
def delete_vehicle(
    project_id: str,
    vehicle_id: str,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.update")),
    db: Session = Depends(get_db),
):
    from app.services.record_lock import lock_writable_project
    from app.services.permissions import authorize_project, C_UPDATE

    lock_writable_project(db, p, user)
    authorize_project(user, p, C_UPDATE)
    v = db.get(Vehicle, vehicle_id)
    if v is None or v.project_id != project_id:
        raise HTTPException(status_code=404, detail="车型不存在")
    from app.services.project_lifecycle import ensure_schedule_writable

    ensure_schedule_writable(p)
    desc = f"删除车型 {v.vehicle_type} {v.model_name}"
    from app.models import VehicleUnit
    from app.services.vehicle_checks import reconcile_vehicle_type
    units=db.query(VehicleUnit).filter_by(project_id=project_id,vehicle_id=v.id).all()
    previous_type=v.vehicle_type
    db.delete(v)
    db.flush()
    checks=reconcile_vehicle_type(db,project_id,units,previous_type)
    if checks:
        log_change(db,project_id,"vehicle_check",vehicle_id,"generate_scope",user.id,
            f"车型删除后真实车辆类型待核对，新增{len(checks)}项适用性待检检查",
            {"vehicle_type":previous_type},{"vehicle_type":None,"check_ids":[c.id for c in checks]})
    from app.services.generate_tasks import recompute_per_vehicle_targets

    recompute_per_vehicle_targets(db, project_id)
    sync_arrival_all(db, p, user.id, "删除车型配置后重新核对整批车辆")
    log_change(db, project_id, "vehicle", vehicle_id, "delete", user.id, desc)
    db.commit()
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return {"message": "车型已删除"}
