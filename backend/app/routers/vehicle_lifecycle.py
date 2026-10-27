"""Physical AGV registry and lifecycle timeline."""

from datetime import date
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission,route_permission_contextual
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Vehicle, VehicleUnit, VehicleLifecycleEvent
from app.services.change_log import log_change
from app.services.project_events import sync_arrival_all
from app.services.permissions import authorize_project, project_capabilities, C_PLAN, C_ISSUES
from app.services.record_lock import lock_writable_project
from app.services.scope import active_co_manager, ensure_project_visible

router = APIRouter(tags=["车辆生命周期"])

STAGES = ("planned", "production", "factory_test", "shipping", "on_site", "commissioning", "running", "maintenance", "retired")
EVENT_TYPES = ("created", "production", "test", "shipment", "arrival", "commission", "handover", "maintenance", "repair", "inspection", "fault", "retire", "other")
ISSUE_EVENT_TYPES = ("fault", "repair", "maintenance", "inspection", "other")


class UnitCreate(BaseModel):
    vehicle_id: Optional[str] = None
    asset_code: str = Field(..., min_length=1, max_length=100)
    serial_number: str = Field(default="", max_length=100)
    fleet_no: str = Field(default="", max_length=30)  # 车号
    current_stage: str = Field(default="planned", pattern="^(planned|production|factory_test|shipping|on_site|commissioning|running|maintenance|retired)$")
    location: str = Field(default="", max_length=200)
    warranty_end: Optional[date] = None
    commissioned_at: Optional[date] = None
    note: str = Field(default="", max_length=1000)


class UnitUpdate(BaseModel):
    serial_number: Optional[str] = None
    fleet_no: Optional[str] = Field(default=None, max_length=30)
    current_stage: Optional[str] = Field(default=None, pattern="^(planned|production|factory_test|shipping|on_site|commissioning|running|maintenance|retired)$")
    current_status: Optional[str] = Field(default=None, pattern="^(normal|attention|fault|stopped|retired)$")
    location: Optional[str] = None
    warranty_end: Optional[date] = None
    commissioned_at: Optional[date] = None
    note: Optional[str] = None


class EventCreate(BaseModel):
    event_type: str = Field(..., pattern="^(created|production|test|shipment|arrival|commission|handover|maintenance|repair|inspection|fault|retire|other)$")
    event_date: date
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    status_after: str = Field(default="", pattern="^(|normal|attention|fault|stopped|retired)$")
    location_after: str = Field(default="", max_length=200)
    attachment_id: Optional[str] = None
    stage_after: Optional[str] = Field(default=None, pattern="^(planned|production|factory_test|shipping|on_site|commissioning|running|maintenance|retired)$")
    fault_part: str = Field(default="", max_length=200)
    cause: str = Field(default="", max_length=2000)
    action_taken: str = Field(default="", max_length=4000)
    replaced_parts: list[dict] = Field(default_factory=list)
    downtime_hours: Optional[float] = Field(default=None, ge=0, le=100000)
    verification: str = Field(default="", max_length=2000)
    handler: str = Field(default="", max_length=100)
    is_closed: bool = False


class EventUpdate(BaseModel):
    attachment_id: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    fault_part: Optional[str] = Field(default=None, max_length=200)
    cause: Optional[str] = Field(default=None, max_length=2000)
    action_taken: Optional[str] = Field(default=None, max_length=4000)
    replaced_parts: Optional[list[dict]] = None
    downtime_hours: Optional[float] = Field(default=None, ge=0, le=100000)
    verification: Optional[str] = Field(default=None, max_length=2000)
    handler: Optional[str] = Field(default=None, max_length=100)
    is_closed: Optional[bool] = None
    status_after: Optional[str] = Field(default=None, pattern="^(normal|attention|fault|stopped|retired)$")


def _update_unit_status(db: Session, unit: VehicleUnit, requested: str) -> None:
    """An individual resolved issue cannot clear another outstanding vehicle fault."""
    db.flush()
    open_events = db.query(VehicleLifecycleEvent).filter(
        VehicleLifecycleEvent.vehicle_unit_id == unit.id,
        VehicleLifecycleEvent.event_type.in_(ISSUE_EVENT_TYPES),
        VehicleLifecycleEvent.is_closed.is_(False),
    ).all()
    priority = {"normal": 0, "attention": 1, "fault": 2, "stopped": 3, "retired": 4}
    status = requested
    for event in open_events:
        outstanding = event.status_after if event.status_after in priority and event.status_after != "normal" else "attention"
        if priority[outstanding] > priority[status]:
            status = outstanding
    unit.current_status = status


def _weekly_event_assignments(db, events, viewer=None):
    from app.models import Task,WeeklyPlanCell,Project
    from app.services.weekly_plans import can_edit
    grouped={}
    if not events:return grouped
    project=db.get(Project,events[0].project_id)
    query=db.query(Task.source_vehicle_event_id,WeeklyPlanCell).join(WeeklyPlanCell,WeeklyPlanCell.task_id==Task.id).filter(
        Task.project_id==project.id,WeeklyPlanCell.project_id==project.id,Task.source_vehicle_event_id.in_([event.id for event in events]))
    if viewer is None or not can_edit(project,viewer):query=query.filter(WeeklyPlanCell.published.is_(True))
    rows=query.order_by(WeeklyPlanCell.week_start,WeeklyPlanCell.id).all()
    people={person.id:person.display_name for person in db.query(User).filter(User.id.in_({identity for _,cell in rows for identity in cell.assignee_ids or []}))}
    for event_id,cell in rows:
        grouped.setdefault(event_id,[]).append({'id':cell.id,'task_id':cell.task_id,'week_start':cell.week_start.isoformat(),
            'assignees':[{'id':identity,'name':people.get(identity,'原负责人未记录')} for identity in cell.assignee_ids or []],
            'published':cell.published,'is_cancelled':cell.is_cancelled})
    return grouped


def _event_dict(db: Session, event: VehicleLifecycleEvent, viewer=None, *, weekly=None) -> dict:
    operator = db.get(User, event.operator_id) if event.operator_id else None
    if weekly is None:weekly=_weekly_event_assignments(db,[event],viewer).get(event.id,[])
    return {
        "id": event.id,
        "weekly_assignments":weekly,
        "event_type": event.event_type,
        "event_date": event.event_date.isoformat(),
        "title": event.title,
        "description": event.description,
        "fault_part": event.fault_part or "",
        "cause": event.cause or "",
        "action_taken": event.action_taken or "",
        "replaced_parts": event.replaced_parts or [],
        "downtime_hours": event.downtime_hours,
        "verification": event.verification or "",
        "handler": event.handler or "",
        "is_closed": bool(event.is_closed),
        "stage_after": event.stage_after,
        "status_after": event.status_after,
        "location_after": event.location_after,
        "attachment_id": event.attachment_id,
        "operator_id": event.operator_id,
        "operator_name": operator.display_name if operator else "",
        "extra": event.extra or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


def _unit_dict(
    db: Session,
    unit: VehicleUnit,
    include_events: bool = False,
    vehicle_map: Optional[dict[str, Vehicle]] = None,
    issue_summary: Optional[tuple[int, int, Optional[date]]] = None,
    viewer=None,
) -> dict:
    vehicle = (vehicle_map.get(unit.vehicle_id) if vehicle_map is not None else db.get(Vehicle, unit.vehicle_id)) if unit.vehicle_id else None
    result = {
        "id": unit.id,
        "project_id": unit.project_id,
        "vehicle_id": unit.vehicle_id,
        "vehicle_type": vehicle.vehicle_type if vehicle else "",
        "model_name": vehicle.model_name if vehicle else (unit.model_name or ""),
        "asset_code": unit.asset_code,
        "serial_number": unit.serial_number,
        "fleet_no": unit.fleet_no or "",
        "current_stage": unit.current_stage,
        "legacy_current_stage": unit.legacy_current_stage,
        "current_status": unit.current_status,
        "location": unit.location,
        "warranty_end": unit.warranty_end.isoformat() if unit.warranty_end else None,
        "commissioned_at": unit.commissioned_at.isoformat() if unit.commissioned_at else None,
        "arrived_at": unit.arrived_at.isoformat() if unit.arrived_at else None,
        "note": unit.note,
        "created_at": unit.created_at.isoformat() if unit.created_at else None,
    }
    issue_events = None
    if include_events:
        issue_events = db.query(VehicleLifecycleEvent).filter(
            VehicleLifecycleEvent.vehicle_unit_id == unit.id,
            VehicleLifecycleEvent.event_type.in_(ISSUE_EVENT_TYPES),
        ).order_by(VehicleLifecycleEvent.event_date.desc(), VehicleLifecycleEvent.created_at.desc()).all()
        weekly=_weekly_event_assignments(db,issue_events,viewer)
        result["events"] = [_event_dict(db, event,viewer,weekly=weekly.get(event.id,[])) for event in issue_events]
        from app.models import Task, ScheduleEntry
        assignments = db.query(Task.source_vehicle_event_id, ScheduleEntry, User.display_name).join(
            ScheduleEntry, ScheduleEntry.task_id == Task.id).outerjoin(User, User.id == ScheduleEntry.assignee_id).filter(
            Task.project_id == unit.project_id, ScheduleEntry.project_id == unit.project_id, Task.source_vehicle_event_id.in_([event.id for event in issue_events]),
            ScheduleEntry.status != 'skipped').order_by(ScheduleEntry.work_date).all()
        by_event = {}
        for event_id, entry, name in assignments:
            by_event.setdefault(event_id, []).append({'id': entry.id, 'work_date': entry.work_date.isoformat(),
                'assignee_name': name or '待分配', 'task_id': entry.task_id, 'status': entry.status,'read_only_source':True})
        for row in result['events']:
            row['assignments'] = by_event.get(row['id'], [])
    if issue_summary is not None:
        issue_count, open_issue_count, last_issue_date = issue_summary
    else:
        if issue_events is None:
            issue_events = db.query(VehicleLifecycleEvent).filter(
                VehicleLifecycleEvent.vehicle_unit_id == unit.id,
                VehicleLifecycleEvent.event_type.in_(ISSUE_EVENT_TYPES),
            ).all()
        issue_count = len(issue_events)
        open_issue_count = sum(1 for event in issue_events if not event.is_closed)
        last_issue_date = max((event.event_date for event in issue_events), default=None)
    result["issue_count"] = issue_count
    result["open_issue_count"] = open_issue_count
    result["last_issue_date"] = last_issue_date
    if result["last_issue_date"]:
        result["last_issue_date"] = result["last_issue_date"].isoformat()
    return result


def _editable(db: Session, project_id: str, user: User):
    project = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, project, user)
    authorize_project(user, project, C_PLAN)
    return project


def _can_record(db: Session, project_id: str, user: User):
    from app.services.system_permissions import has_permission
    if not has_permission(user, "worker.issues", default=True):
        raise HTTPException(403, "现场问题记录权限已被系统管理员撤销")
    project = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, project, user)
    if user.role in ("admin", "director") or project.manager == user.id or project.technical_manager == user.id:
        return project
    if user.id in (project.members or []):
        return project
    raise HTTPException(status_code=403, detail="只有项目成员可以记录车辆现场问题")


@router.get("/projects/{project_id}/vehicle-units")
@route_permission('project.read')
def list_units(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    units = db.query(VehicleUnit).filter_by(project_id=project_id).order_by(VehicleUnit.asset_code).all()
    vehicle_ids = {unit.vehicle_id for unit in units if unit.vehicle_id}
    vehicle_map = {vehicle.id: vehicle for vehicle in db.query(Vehicle).filter(Vehicle.id.in_(vehicle_ids)).all()} if vehicle_ids else {}
    summaries = (db.query(
        VehicleLifecycleEvent.vehicle_unit_id,
        func.count(VehicleLifecycleEvent.id),
        func.sum(case((VehicleLifecycleEvent.is_closed.is_(False), 1), else_=0)),
        func.max(VehicleLifecycleEvent.event_date),
    ).filter(
        VehicleLifecycleEvent.project_id == project_id,
        VehicleLifecycleEvent.event_type.in_(ISSUE_EVENT_TYPES),
    ).group_by(VehicleLifecycleEvent.vehicle_unit_id).all())
    summary_map = {unit_id: (count, open_count or 0, last_date) for unit_id, count, open_count, last_date in summaries}
    return [_unit_dict(db, unit, vehicle_map=vehicle_map, issue_summary=summary_map.get(unit.id, (0, 0, None))) for unit in units]


@router.post("/projects/{project_id}/vehicle-units")
@route_permission('project.manage_plan')
def create_unit(project_id: str, body: UnitCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _editable(db, project_id, user)
    if body.current_stage != "planned":
        raise HTTPException(400, "车辆当前环节由车辆进度表推导，不能手动维护")
    if body.vehicle_id:
        vehicle = db.get(Vehicle, body.vehicle_id)
        if vehicle is None or vehicle.project_id != project_id:
            raise HTTPException(status_code=400, detail="车型不属于当前项目")
    if db.query(VehicleUnit).filter_by(project_id=project_id, asset_code=body.asset_code).first():
        raise HTTPException(status_code=400, detail="项目内车辆编号不能重复")
    unit = VehicleUnit(project_id=project_id, **body.model_dump())
    db.add(unit)
    db.flush()
    event = VehicleLifecycleEvent(
        vehicle_unit_id=unit.id, project_id=project_id, event_type="created", event_date=date.today(),
        title="建立车辆档案", status_after="normal", location_after=unit.location, operator_id=user.id,
    )
    db.add(event)
    log_change(db, project_id, "vehicle_unit", unit.id, "create", user.id, f"建立车辆档案：{unit.asset_code}")
    from app.services.vehicle_checks import generate_for_units
    checks = generate_for_units(db, project_id, [unit])
    if checks:
        log_change(db, project_id, "vehicle_check", unit.id, "generate", user.id, f"为新增实车生成{len(checks)}项待检检查")
    sync_arrival_all(db, project, user.id, "车辆建档后重新核对整批车辆")
    from app.services.project_documents import materialize_static
    materialize_static(db, project)
    db.commit()
    db.refresh(unit)
    return _unit_dict(db, unit, True,viewer=user)


@router.get("/projects/{project_id}/vehicle-units/{unit_id}")
@route_permission('project.read')
def get_unit(project_id: str, unit_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    unit = db.get(VehicleUnit, unit_id)
    if unit is None or unit.project_id != project_id:
        raise HTTPException(status_code=404, detail="车辆档案不存在")
    return _unit_dict(db, unit, True,viewer=user)


@router.put("/projects/{project_id}/vehicle-units/{unit_id}")
@route_permission('project.manage_plan')
def update_unit(project_id: str, unit_id: str, body: UnitUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _editable(db, project_id, user)
    unit = db.get(VehicleUnit, unit_id)
    if unit is None or unit.project_id != project_id:
        raise HTTPException(status_code=404, detail="车辆档案不存在")
    if "current_stage" in body.model_fields_set:
        raise HTTPException(400, "车辆当前环节由车辆进度表推导，不能手动维护")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(unit, field, value)
    if body.current_status is not None:
        _update_unit_status(db, unit, body.current_status)
    log_change(db, project_id, "vehicle_unit", unit.id, "update", user.id, f"更新车辆档案：{unit.asset_code}")
    db.commit()
    db.refresh(unit)
    return _unit_dict(db, unit)


@router.post("/projects/{project_id}/vehicle-units/{unit_id}/events")
@route_permission('worker.issues')
def create_event(project_id: str, unit_id: str, body: EventCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _can_record(db, project_id, user)
    unit = db.get(VehicleUnit, unit_id)
    if unit is None or unit.project_id != project_id:
        raise HTTPException(status_code=404, detail="车辆档案不存在")
    if body.attachment_id:
        from app.models import Attachment
        attachment = db.get(Attachment, body.attachment_id)
        if attachment is None or attachment.project_id != project_id:
            raise HTTPException(400, "车辆事件附件不属于当前项目或已删除")
    data = body.model_dump()
    event = VehicleLifecycleEvent(vehicle_unit_id=unit.id, project_id=project_id, operator_id=user.id, **data)
    db.add(event)
    if body.status_after or body.event_type in ISSUE_EVENT_TYPES:
        _update_unit_status(db, unit, body.status_after or unit.current_status)
    if body.location_after:
        unit.location = body.location_after
    log_change(db, project_id, "vehicle_unit", unit.id, "update", user.id, f"车辆事件：{body.title}")
    db.commit()
    db.refresh(event)
    return _event_dict(db, event,user)


@router.put("/projects/{project_id}/vehicle-units/{unit_id}/events/{event_id}")
@route_permission('worker.issues')
def update_event(
    project_id: str, unit_id: str, event_id: str, body: EventUpdate,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    project = _can_record(db, project_id, user)
    event = db.get(VehicleLifecycleEvent, event_id)
    if event is None or event.project_id != project_id or event.vehicle_unit_id != unit_id:
        raise HTTPException(status_code=404, detail="车辆问题记录不存在")
    can_manage = (
        user.role in ("admin", "director")
        or project.manager == user.id
        or project.technical_manager == user.id
        or active_co_manager(project, user.id)
        or C_ISSUES in project_capabilities(user, project)
    )
    if event.operator_id != user.id and not can_manage:
        raise HTTPException(status_code=403, detail="只能修改自己记录的现场问题")
    if body.attachment_id:
        from app.models import Attachment
        attachment = db.get(Attachment, body.attachment_id)
        if attachment is None or attachment.project_id != project_id:
            raise HTTPException(400, "车辆事件附件不属于当前项目或已删除")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    unit = db.get(VehicleUnit, unit_id)
    if body.status_after is not None or body.is_closed is not None:
        _update_unit_status(db, unit, body.status_after or unit.current_status)
    log_change(db, project_id, "vehicle_unit", unit_id, "update", user.id, f"更新车辆问题：{event.title}")
    db.commit()
    db.refresh(event)
    return _event_dict(db, event,user)


@router.post('/projects/{project_id}/vehicle-units/{unit_id}/events/{event_id}/schedule')
@route_permission('project.manage_schedule')
def retired_repair_schedule(project_id: str, unit_id: str, event_id: str,
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    raise HTTPException(410, '按天维修安排已退休，请将真实维修工作加入周计划')


class RepairWeeklyBody(BaseModel):
    model_config={'extra':'forbid'}
    week_start: date
    assignee_ids: list[str] = Field(default_factory=list,max_length=100)
    mode: Literal['finish','in_progress'] = 'in_progress'
    notes: str = Field(default='',max_length=4000)


@router.post('/projects/{project_id}/vehicle-units/{unit_id}/events/{event_id}/weekly-plans')
@route_permission_contextual('project.manage_schedule','project.manage_plan',reason='周计划需调度权限；首次建立维修工作还需工作项维护权限，锁后逐项校验')
def plan_repair_week(project_id: str, unit_id: str, event_id: str, body: RepairWeeklyBody,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services import weekly_plans
    from app.services.work_assignment import create_repair_work
    from sqlalchemy.exc import IntegrityError
    project=weekly_plans.lock_authority(db,ensure_project_visible(db,project_id,user),user,assignees=body.assignee_ids)
    event=db.get(VehicleLifecycleEvent,event_id,populate_existing=True)
    unit=db.get(VehicleUnit,unit_id,populate_existing=True)
    if not event or not unit or event.project_id!=project_id or unit.project_id!=project_id or event.vehicle_unit_id!=unit_id:
        raise HTTPException(404,'车辆问题不存在')
    if event.event_type not in ISSUE_EVENT_TYPES:raise HTTPException(400,'请选择真实现场车辆问题记录')
    try:
        task,created=create_repair_work(db,project,user,event,unit,body.notes)
        cell=weekly_plans.create(db,project,user,{'task_id':task.id,'week_start':body.week_start,'mode':body.mode,
            'assignee_ids':body.assignee_ids,'notes':body.notes},already_locked=True)
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'维修工作或周计划已由其他操作更新，请刷新核对') from None
    from app.services.cache import cache_clear
    cache_clear('dashboard:')
    return {'cell':weekly_plans.serialize_cell(db,project,cell,user),'task_id':task.id,'created':created,
            'message':'维修周计划初稿已建立；未自动发布，未改原处理人或完成事实'}
