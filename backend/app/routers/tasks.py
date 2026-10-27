"""Project task tree routes: modules, generation, tasks, check items."""

from app.services.system_permissions import route_permission, route_permission_contextual
from app.time_utils import utcnow
from typing import Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_pm
from app.services.vehicle_checks import vehicle_label
from app.services.work_items import item_dict as work_item_dict
from app.models import User, Project, Phase, Module, Task, CheckItem, DailyProgress, ScheduleEntry
from app.routers.projects import get_project_or_404
from app.services.permissions import require_project_capability, authorize_project, C_PLAN
from app.services.scope import ensure_project_visible
from app.services.generate_tasks import generate_tasks_for_modules, selected_execution_module_ids
from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES
from app.services.project_lifecycle import TERMINAL_PROJECT_STATUSES
from app.services.change_log import log_change
from app.services.project_events import planned_event_date
from app.services.system_permissions import has_permission

router = APIRouter(tags=["任务"])


# ===== Modules =====

@router.get("/projects/{project_id}/modules")
@route_permission('project.read')
def list_modules(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List modules for the project: core + extra, with selection state."""
    ensure_project_visible(db, project_id, user)
    # Default template modules as the catalog (multi-template safe).
    # C2-5：条件模块（「项目准备」阶段）不再整体排除——返回并标注 prep_only，
    # 前端展示「仅准备项」标识，让 PM 明白勾选它们只产准备项、不产执行任务。
    template_modules = (
        db.query(Module)
        .join(Phase, Phase.id == Module.phase_id)
        .filter(Module.project_id.is_(None), Module.template_id.is_(None))
        .order_by(Phase.sort_order, Module.sort_order)
        .all()
    )
    # Project-selected modules: match by name (project modules get fresh UUIDs on generation)
    proj_modules = db.query(Module).filter(Module.project_id == project_id).all()
    proj_names = {m.name for m in proj_modules}
    return [
        {
            "id": m.id,
            "name": m.name,
            "category": m.category,
            "phase_name": db.get(Phase, m.phase_id).name if m.phase_id else "",
            "sort_order": m.sort_order,
            "is_selected": m.name in proj_names,
            "prep_only": (db.get(Phase, m.phase_id).name if m.phase_id else "") in REMINDER_ONLY_PHASE_NAMES,
        }
        for m in template_modules
    ]


class GenerateTasksBody(BaseModel):
    module_ids: list[str] = Field(default_factory=list, max_length=500)
    work_item_ids: list[str] = Field(default_factory=list, max_length=2000)
    template_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    exclude_task_ids: list[str] = Field(default_factory=list, max_length=2000)
    exclude_task_names: list[str] = Field(default_factory=list)
    task_quantities: dict[str, Annotated[float, Field(ge=0, allow_inf_nan=False)]] = Field(default_factory=dict)


@router.post("/projects/{project_id}/tasks/generate")
@route_permission('project.manage_plan')
def generate_tasks(
    project_id: str,
    body: GenerateTasksBody,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.manage_plan")),
    db: Session = Depends(get_db),
):
    """Generate project tasks from selected template modules."""
    _lock_task_plan(db, p, user)
    # C2-6：状态守卫——终态项目（已完成/已归档）禁止再生成任务；
    # 日程已确认下达的项目同样禁止（避免改完日程又冒出新任务，破坏已下达排程）。
    if p.status in TERMINAL_PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"项目状态为「{p.status}」，不能再生成任务")
    confirmed = db.query(ScheduleEntry.id).filter(
        ScheduleEntry.project_id == project_id, ScheduleEntry.is_confirmed == True  # noqa: E712
    ).first()
    if confirmed:
        raise HTTPException(status_code=400, detail="日程已确认下达，不能再生成任务（如需调整请先修改排程）")
    from app.services.project_templates import project_template_info
    source = project_template_info(db, p)
    template_id = body.template_id or source['id'] or 'default'
    exclude_task_names = body.exclude_task_names
    task_quantities = body.task_quantities
    try:
        from app.services.work_items import selected_template_work
        selected=selected_template_work(db,template_id,body.work_item_ids or body.module_ids,body.exclude_task_ids,exclude_task_names)
        module_ids=[t.id for t in selected]
    except ValueError as error:
        raise HTTPException(400, str(error))
    if not module_ids:
        return {"message": "所选模块均为「仅准备项」，未生成执行任务",
                "tasks": 0, "check_items": 0, "modules": [], "prep_only": True}
    try:
        result = generate_tasks_for_modules(db, p, module_ids, template_id, [], task_quantities, [])
        # 独立准备清单只负责提醒，不生成执行任务。
        from app.routers.preparations import sync_preparation_items, seed_default_preparations
        from app.services.preparation_scope import conditions_for_scope
        added_conditions = conditions_for_scope(db, template_id, module_ids, [], [])
        p.prep_conditions = sorted(set(p.prep_conditions or []) | set(added_conditions))
        added_preps = seed_default_preparations(db, p.id, dict.fromkeys(p.prep_conditions, True), planned_event_date(db, p.id))
        if added_preps:
            log_change(db, p.id, "preparation", p.id, "generate", user.id, f"随实施范围补充 {added_preps} 项准备事项")
        sync_preparation_items(db, p.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.flush()
    log_change(db, project_id, "task", project_id, "generate", user.id,
               f"生成实施任务：{result['tasks']} 个任务，{result['check_items']} 个检查项")
    # 生成任务不改变项目状态：草稿/准备中等初始状态由用户选定，仅在日程确认后推进。
    db.commit()
    from app.services.cache import cache_clear
    cache_clear("dashboard:")
    return {"message": f"生成 {result['tasks']} 个任务、{result['check_items']} 个检查项", **result}


# ===== Task tree =====

def _task_dict(t: Task, completed: float = 0, db: Session | None = None) -> dict:
    d = {
        "id": t.id,
        "module_id": t.module_id,
        "phase_id": t.phase_id, "group_label": t.group_label or "",
        "kind": "vehicle" if t.quantity_type=="per_vehicle" else "other",
        "is_completed": bool(t.manually_completed),
        "source_task_id": t.source_task_id,
        "name": t.name,
        "description": t.description,
        "quantity_type": t.quantity_type, "vehicle_step_key": t.vehicle_step_key,
        "target_quantity": t.target_quantity,
        "unit": t.unit,
        "standard_hours": t.standard_hours,
        "safety_flag": t.safety_flag,
        "completed": completed,
        "remaining": max(0, (t.target_quantity or 0) - completed),
        "reference_docs": t.reference_docs or [],
        "version": t.version or 0,
    }
    # HYPE-71「直接完成」：手动完成状态 + 操作人/角色/时间/原因（db 传入时解析操作人姓名）
    d["manually_completed"] = bool(t.manually_completed)
    d["manual_completed_by"] = t.manual_completed_by
    d["manual_completed_role"] = t.manual_completed_role
    d["manual_completed_at"] = t.manual_completed_at.isoformat() if t.manual_completed_at else None
    d["manual_completed_reason"] = t.manual_completed_reason or ""
    d["manual_check_overrides"] = t.manual_check_overrides or []
    if db is not None and t.manual_completed_by:
        op = db.get(User, t.manual_completed_by)
        d["manual_completed_by_name"] = op.display_name if op else ""
    else:
        d["manual_completed_by_name"] = ""
    return d


@router.get("/projects/{project_id}/tree")
@route_permission('project.read')
def get_project_tree(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return the project's full task tree: phases → modules → tasks → check items."""
    p = ensure_project_visible(db,project_id,user)
    from sqlalchemy import or_
    from app.services.work_items import phase_of,group_of,item_dict
    completed={tid:qty or 0 for tid,qty in db.query(DailyProgress.task_id,func.sum(DailyProgress.completed_quantity)).filter_by(project_id=project_id).group_by(DailyProgress.task_id)}
    grouped={}
    for task in db.query(Task).filter_by(project_id=project_id).order_by(Task.sort_order,Task.id):
        phase=phase_of(db,task)
        if phase is None:continue
        row=grouped.setdefault(phase.id,{'id':phase.id,'name':phase.name,'sort_order':phase.sort_order or 0,'color':phase.color,'entry_criteria':phase.entry_criteria,'exit_criteria':phase.exit_criteria,'modules':[],'work_items':[]})
        scope=group_of(db,task)
        group=next((m for m in row['modules'] if m['name']==scope),None)
        if group is None:
            group={'id':task.module_id,'name':scope,'category':'source','sort_order':0,'read_only_source':True,'tasks':[]}
            row['modules'].append(group)
        checks=db.query(CheckItem).filter(CheckItem.task_id==task.id,or_(CheckItem.project_id==project_id,CheckItem.project_id.is_(None))).order_by(CheckItem.sort_order,CheckItem.id).all()
        group['tasks'].append({**_task_dict(task,completed.get(task.id,0),db),'check_items':[{'id':c.id,'name':c.name,'description':c.description or '',
            'vehicle_unit_id':c.vehicle_unit_id,'vehicle_step_key':c.vehicle_step_key,'vehicle_label':vehicle_label(db,c),
            'is_required':c.is_required,'is_safety_critical':c.is_safety_critical,'is_applicable':c.is_applicable,'is_done':c.is_done,
            'failed':c.failed,'failed_reason':c.failed_reason,'not_applicable_reason':c.not_applicable_reason,'done_by':c.done_by,
            'done_at':c.done_at.isoformat() if c.done_at else None,'version':c.version or 0} for c in checks]})
        row['work_items'].append(item_dict(db,task,checks=True))
    return sorted(grouped.values(),key=lambda phase:(phase['sort_order'],phase['id']))


# ===== Single task create (Linear 式快速添加) =====

@router.get("/projects/{project_id}/handover-summary")
@route_permission('project.read')
def handover_summary(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Reference existing work for a handover, without creating duplicate tasks."""
    from app.models import Issue, VehicleLifecycleEvent, VehicleUnit
    from app.services.progress import execution_tasks, task_progress_maps, project_completion_blocker_tasks
    from app.services.acceptance import acceptance_summary
    p = ensure_project_visible(db, project_id, user)
    tasks = execution_tasks(db, project_id)
    _, _, progress = task_progress_maps(db, tasks)
    blocked_ids = {t.id for t in project_completion_blocker_tasks(db, project_id)}
    pending = sorted((t for t in tasks if progress.get(t.id, 0) < 100 or t.id in blocked_ids), key=lambda t: (t.sort_order, t.id))
    issues = db.query(Issue).filter(Issue.project_id == project_id, Issue.status.in_(["open", "processing"])).order_by(Issue.id).all()
    faults = db.query(VehicleLifecycleEvent, VehicleUnit.asset_code).join(VehicleUnit, VehicleUnit.id == VehicleLifecycleEvent.vehicle_unit_id).filter(
        VehicleLifecycleEvent.project_id == project_id, VehicleLifecycleEvent.event_type == "fault", VehicleLifecycleEvent.is_closed.is_(False)).order_by(VehicleLifecycleEvent.event_date).all()
    from app.models import ProjectDocument
    document_rows = db.query(ProjectDocument).filter_by(project_id=project_id,status='pending').all()
    from app.services.project_documents import can_read_document, applicable, iso
    documents = [{"id":row.id,"code":row.code,"name":row.name,"status":row.status,"due_at":iso(row.due_at),"vehicle_label":row.vehicle_label}
        for row in document_rows if applicable(p,row) and can_read_document(user,p,row)]
    return {"acceptance_summary": acceptance_summary(db, project_id), "project_name": p.name, "counts": {"tasks": len(pending), "issues": len(issues), "faults": len(faults), "documents": len(documents)},
            "tasks": [{"id": t.id, "name": t.name} for t in pending[:15]],
            "issues": [{"id": i.id, "title": i.title} for i in issues[:10]],
            "faults": [{"id": e.id, "unit_id": e.vehicle_unit_id, "asset_code": code, "title": e.title} for e, code in faults[:10]],
            "documents": documents[:15]}

@router.get("/projects/{project_id}/tasks/{task_id}/workspace")
@route_permission('project.read')
def task_workspace(project_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One work item with its arrangements and execution history, from any view."""
    from app.models import VehicleLifecycleEvent, VehicleUnit
    from app.services.permissions import project_capabilities, C_PLAN, C_SCHEDULE, C_ISSUES
    from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
    from app.services.scope import active_co_manager
    from app.services.progress import task_completed
    p = ensure_project_visible(db, project_id, user)
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(404, "任务不存在")
    module = db.get(Module, task.module_id) if task.module_id else None
    from app.services.work_items import phase_of
    phase = phase_of(db,task)
    caps = project_capabilities(user, p)
    from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES
    active = p.status in EXECUTION_PROJECT_STATUSES and phase is not None and phase.name not in REMINDER_ONLY_PHASE_NAMES
    checks = db.query(CheckItem).filter_by(project_id=project_id, task_id=task_id).order_by(CheckItem.sort_order).all()
    entries = db.query(ScheduleEntry, User.display_name).outerjoin(User, User.id == ScheduleEntry.assignee_id).filter(
        ScheduleEntry.project_id == project_id, ScheduleEntry.task_id == task_id).order_by(ScheduleEntry.work_date, ScheduleEntry.id).all()
    reports = db.query(DailyProgress, User.display_name).outerjoin(User, User.id == DailyProgress.user_id).filter(
        DailyProgress.project_id == project_id, DailyProgress.task_id == task_id).order_by(DailyProgress.created_at.desc(), DailyProgress.id).limit(30).all()
    event = db.get(VehicleLifecycleEvent, task.source_vehicle_event_id) if task.source_vehicle_event_id else None
    if event and event.project_id != project_id:
        event = None
    repair = None
    if event:
        from app.routers.vehicle_lifecycle import _event_dict
        unit = db.get(VehicleUnit, event.vehicle_unit_id)
        repair = {**_event_dict(db, event,user), "unit_id": event.vehicle_unit_id, "asset_code": unit.asset_code if unit else "", "current_status": unit.current_status if unit else ""}
    member = user.id in (p.members or []) or user.id in (p.manager,p.technical_manager)
    recorder = user.role in ("admin", "director") or user.id in (p.manager, p.technical_manager) or member
    return {
        "project": {"id": p.id, "name": p.name, "status": p.status, "timezone": p.timezone or "Asia/Shanghai", "capabilities": sorted(caps)},
        "work_item": work_item_dict(db,task,checks=True),
        "can_override": C_PLAN in caps,
        "can_complete": active and has_permission(user,"worker.report",default=True) and (C_PLAN in caps or member),
        "task": {**_task_dict(task, task_completed(db, task_id), db), "phase_name": phase.name if phase else "", "module_name": module.name if module else "",
                 "check_items": [{"id": c.id, "name": c.name, "vehicle_unit_id": c.vehicle_unit_id, "vehicle_label": vehicle_label(db,c), "vehicle_step_key": c.vehicle_step_key, "source_definition_id": c.vehicle_check_definition_id, "definition_version": c.definition_version, "description": c.description or "", "is_required": c.is_required,
                   "is_safety_critical": c.is_safety_critical, "is_applicable": c.is_applicable, "not_applicable_reason": c.not_applicable_reason,
                   "is_done": c.is_done, "failed": c.failed, "failed_reason": c.failed_reason, "version": c.version or 0} for c in checks]},
        "entries": [{"id": e.id, "task_id": task_id, "task_name": task.name, "project_id": project_id, "assignee_id": e.assignee_id,
                     "assignee_name": name or "未分配", "work_date": e.work_date.isoformat(), "planned_quantity": e.planned_quantity,
                     "notes": e.notes, "is_confirmed": e.is_confirmed, "status": e.status, "version": e.version or 0} for e, name in entries],
        "reports": [{"id": r.id, "work_date": r.work_date.isoformat(), "user_name": name or "历史人员", "quantity": r.completed_quantity,
                     "note": r.note, "created_at": r.created_at.isoformat() + "+00:00" if r.created_at else None} for r, name in reports],
        "repair": repair,
        "can_schedule": active and C_SCHEDULE in caps,
        "can_report": active and (member or user.role in ("pm", "admin")) and has_permission(user, "worker.report", default=True),
        "can_check": active and (C_PLAN in caps or (user.role == "worker" and member)) and has_permission(user, "worker.report", default=True),
        "can_update_repair": bool(active and event and recorder and has_permission(user, "worker.issues", default=True) and (event.operator_id == user.id or user.role in ("admin", "director") or user.id in (p.manager, p.technical_manager) or active_co_manager(p, user.id) or C_ISSUES in caps)),
    }

class TaskCreate(BaseModel):
    module_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    quantity_type: str = Field(default="manual", pattern="^(per_vehicle|manual|fixed)$")
    target_quantity: Optional[float] = Field(allow_inf_nan=False, default=None, ge=0)
    unit: str = "项"
    standard_hours: Optional[float] = Field(allow_inf_nan=False, default=None, ge=0)
    safety_flag: bool = False
    vehicle_step_key: Optional[str] = Field(default=None, max_length=80)


@router.post("/projects/{project_id}/tasks")
@route_permission('project.manage_plan')
def create_single_task(
    project_id: str,
    data: TaskCreate,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.manage_plan")),
    db: Session = Depends(get_db),
):
    """快速添加单个任务到项目的某个模块（Linear/Jira 式）。"""
    from app.services.work_items import lock_plan
    lock_plan(db,p,user)
    m = db.get(Module, data.module_id)
    if m is None or m.project_id != project_id:
        raise HTTPException(status_code=404, detail="模块不存在")
    from app.services.work_items import assert_phase
    mapped={value for (value,) in db.query(Task.phase_id).filter_by(project_id=project_id,module_id=m.id) if value}
    phase=db.get(Phase,m.phase_id) if m.phase_id else None
    phase_id=phase.id if phase and phase.project_id==project_id else next(iter(mapped)) if len(mapped)==1 else None
    if phase_id is None:raise HTTPException(400,'历史模块已不作为工作归属，请在工作项中明确选择项目阶段')
    assert_phase(db,phase_id,project_id=project_id)
    t=Task(project_id=project_id,phase_id=phase_id,module_id=None,group_label=m.name,name=data.name,
        quantity_type='per_vehicle' if data.quantity_type=='per_vehicle' else 'fixed',target_quantity=None,
        unit='台' if data.quantity_type=='per_vehicle' else '项',safety_flag=data.safety_flag,
        legacy_work_snapshot={'kind':'legacy_client_work_definition','module_id':m.id,
            'quantity':{'type':data.quantity_type,'target':data.target_quantity,'unit':data.unit,'standard_hours':data.standard_hours}},
        sort_order=(db.query(func.max(Task.sort_order)).filter_by(project_id=project_id,phase_id=phase_id).scalar() or 0)+1)
    from app.services.vehicle_checks import validate_step
    if data.quantity_type=='per_vehicle' and not data.vehicle_step_key:raise HTTPException(400,'车辆工作须明确关联真实车辆环节')
    t.vehicle_step_key=validate_step(db,t,data.vehicle_step_key)
    db.add(t)
    db.flush()
    log_change(db, project_id, "task", t.id, "create", user.id, f"添加任务「{t.name}」")
    db.commit()
    return {"id":t.id,"name":t.name,"target_quantity":None,"message":"工作项已添加；原数量输入仅保留来源"}


# ===== Task update =====

def _lock_task_plan(db: Session, project: Project, user: User) -> None:
    """Planning and execution serialize on the same project before revalidation."""
    from app.services.record_lock import lock_writable_project
    lock_writable_project(db, project, user)
    db.refresh(user)
    from app.services.system_permissions import has_permission
    if not has_permission(user, "project.manage_plan", default=True):
        raise HTTPException(403, "工作计划维护权限已变化")
    authorize_project(user, project, C_PLAN)
    if project.status in TERMINAL_PROJECT_STATUSES:
        raise HTTPException(400, "已结束的项目不能调整任务计划，请先恢复到验收中")


def _validate_target_actuals(db: Session, task: Task, target: float) -> None:
    completed = db.query(func.coalesce(func.sum(DailyProgress.completed_quantity), 0)).filter(
        DailyProgress.task_id == task.id).scalar() or 0
    if target < completed - 1e-9:
        raise HTTPException(400, f"目标数量不能低于已填报的实际完成量（{completed:g} {task.unit}），请先核对并修正报工")


def _validate_target_withdrawal(db: Session, task: Task) -> None:
    """Withdraw unexecuted work without erasing reporting or schedule history."""
    # A correcting report can bring the sum back to zero. Its original execution
    # is still part of the audit trail, so a SUM-only check is insufficient.
    if db.query(DailyProgress.id).filter(DailyProgress.task_id == task.id).first():
        raise HTTPException(400, "已有报工记录，不能清空目标数量；请保留目标并核对报工")
    if task.manually_completed:
        raise HTTPException(400, "任务已手动完成，不能清空目标数量；请先取消手动完成")
    protected = db.query(ScheduleEntry.id).filter(
        ScheduleEntry.task_id == task.id,
        or_(ScheduleEntry.status.is_(None), ScheduleEntry.status != "skipped"),
        or_(ScheduleEntry.is_confirmed.is_(True), ScheduleEntry.is_locked.is_(True), ScheduleEntry.status == "done"),
    ).first()
    if protected:
        raise HTTPException(400, "任务有已下达、锁定或已完成的工作安排，不能清空目标数量；请先在项目日程核对或取消未完成的安排、解除锁定，保留已完成记录")




class TaskUpdate(BaseModel):
    target_quantity: Optional[float] = Field(allow_inf_nan=False, default=None, ge=0)
    unit: Optional[str] = None
    standard_hours: Optional[float] = Field(allow_inf_nan=False, default=None, ge=0)
    name: Optional[str] = None
    deliverables: Optional[list] = None
    vehicle_step_key: Optional[str] = Field(default=None, max_length=80)
    module_id: Optional[str] = None  # 看板拖拽：直接指定目标模块
    phase_id: Optional[str] = None   # 看板拖拽：指定目标阶段，自动落到该阶段首个模块
    version: Optional[int] = None  # 乐观锁版本号


@router.put("/projects/{project_id}/tasks/{task_id}")
@route_permission('project.manage_plan')
def update_task(
    project_id: str,
    task_id: str,
    data: TaskUpdate,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.manage_plan")),
    db: Session = Depends(get_db),
):
    """PM updates a task (e.g. fill target quantity for manual tasks)."""
    _lock_task_plan(db, p, user)
    t = db.get(Task, task_id)
    if t is None or t.project_id != project_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    from app.services.record_lock import lock_record
    lock_record(db, t, conflict_detail="任务正由另一操作更新，请刷新后重试")
    from app.services.optimistic import bump_version
    bump_version(t, data.version)
    old = _task_dict(t)
    if t.phase_id is not None:
        from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES
        if p.status not in ACTIVE_PROJECT_STATUSES:raise HTTPException(400,'当前项目状态不能维护工作定义')
        if data.model_fields_set & {'target_quantity','unit','standard_hours','module_id'}:
            raise HTTPException(400,'原数量与模块来源保持只读；当前工作按阶段、完成状态或真实车辆环节维护')
        if data.model_fields_set & {'phase_id','vehicle_step_key'} and data.version is None:
            raise HTTPException(400,'工作关联变更须提交当前版本号')
        from app.services.work_items import set_definition
        values={key:getattr(data,key) for key in ('name','phase_id','vehicle_step_key') if key in data.model_fields_set}
        set_definition(db,t,values)
        log_change(db,project_id,'task',t.id,'update',user.id,f'修改工作项「{t.name}」',old,_task_dict(t))
        db.commit()
        return _task_dict(t,db=db)
    if "vehicle_step_key" in data.model_fields_set:
        if data.version is None:
            raise HTTPException(400, "关联车辆环节须提交当前工作版本号")
        from app.services.vehicle_checks import bind_step
        bind_step(db, t, data.vehicle_step_key)
    if "target_quantity" in data.model_fields_set:
        # Execution/startup requires a positive target. Explicit zero, like an
        # empty editor, withdraws the target; omission remains a partial update.
        target = data.target_quantity if data.target_quantity else None
        if target is None:
            if t.target_quantity is not None:
                _validate_target_withdrawal(db, t)
        else:
            _validate_target_actuals(db, t, target)
        t.target_quantity = target
    if data.unit is not None:
        t.unit = data.unit
    if data.standard_hours is not None:
        t.standard_hours = data.standard_hours
    if data.name is not None:
        t.name = data.name
    if "deliverables" in data.model_fields_set:
        raise HTTPException(400, "任务交付物已并入项目资料要求，请在资料页维护")
    # —— 看板拖拽：跨阶段/跨模块移动（module_id 与 phase_id 二选一）——
    if data.module_id is not None and data.phase_id is not None:
        raise HTTPException(status_code=400, detail="module_id 与 phase_id 只能传一个")
    target_module = None
    if data.phase_id is not None:
        # 项目模块的 phase_id 指向模板阶段（project_id IS NULL），
        # 因此用「该项目存在挂在该阶段的模块」判定目标阶段，而非 Phase.project_id
        target_module = (
            db.query(Module)
            .filter(Module.project_id == project_id, Module.phase_id == data.phase_id)
            .order_by(Module.sort_order)
            .first()
        )
        if target_module is None:
            raise HTTPException(status_code=404, detail="目标阶段不存在于该项目")
    elif data.module_id is not None:
        target_module = db.get(Module, data.module_id)
        if target_module is None or target_module.project_id != project_id:
            raise HTTPException(status_code=404, detail="目标模块不存在")

    if target_module is not None and target_module.id != t.module_id:
        old_module = db.get(Module, t.module_id)
        t.module_id = target_module.id
        # 追加到目标模块末尾
        max_order = db.query(func.coalesce(func.max(Task.sort_order), 0)).filter(
            Task.project_id == project_id, Task.module_id == target_module.id).scalar()
        t.sort_order = (max_order or 0) + 1
        log_change(db, project_id, "task", t.id, "update", user.id,
                   f"移动任务「{t.name}」：{old_module.name if old_module else '?'} → {target_module.name}",
                   {"module_id": old_module.id, "phase_id": old_module.phase_id},
                   {"module_id": target_module.id, "phase_id": target_module.phase_id})
    db.flush()
    old_target = old['target_quantity'] if old['target_quantity'] else '待确认'
    new_target = t.target_quantity if t.target_quantity else '待确认'
    log_change(db, project_id, "task", t.id, "update", user.id,
               f"更新任务「{t.name}」：目标数量 {old_target} → {new_target} {t.unit}")
    db.commit()
    from app.services.cache import cache_clear
    from app.services.progress import task_completed
    cache_clear("dashboard:")
    return _task_dict(t, task_completed(db, t.id), db)


class TaskTargetItem(BaseModel):
    id: str
    target_quantity: float = Field(gt=0, allow_inf_nan=False)
    version: int = Field(ge=0)


class TaskTargetsBatch(BaseModel):
    items: list[TaskTargetItem] = Field(min_length=1, max_length=500)


@router.put("/projects/{project_id}/task-targets")
@route_permission('project.manage_plan')
def update_task_targets(
    project_id: str,
    data: TaskTargetsBatch,
    user: User = Depends(get_current_user),
    p: Project = Depends(require_project_capability("project.manage_plan")),
    db: Session = Depends(get_db),
):
    """开工清单批量填写工作量；任一越权/冲突时整批回滚。"""
    _lock_task_plan(db, p, user)
    if p.status not in {"preparing", "ready"}:
        raise HTTPException(400, "当前项目不在开工准备阶段，请到任务详情调整工作量")
    if db.query(ScheduleEntry.id).filter(
        ScheduleEntry.project_id == project_id, ScheduleEntry.is_confirmed.is_(True)
    ).first():
        raise HTTPException(400, "日程已下达，请到任务详情调整工作量并核对日程")
    ids = [item.id for item in data.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "不能重复提交同一任务")
    tasks = {task.id: task for task in db.query(Task).filter(Task.project_id == project_id, Task.id.in_(ids)).all()}
    if len(tasks) != len(ids):
        raise HTTPException(404, "任务不存在于当前项目，请刷新工作清单")
    from app.services.optimistic import bump_version
    try:
        for item in data.items:
            task = tasks[item.id]
            if task.phase_id is not None:
                raise HTTPException(400,"工作项不再维护目标数量，原数量保持只读")
            before = task.target_quantity
            _validate_target_actuals(db, task, item.target_quantity)
            bump_version(task, item.version)
            task.target_quantity = item.target_quantity
            log_change(db, project_id, "task", task.id, "update", user.id,
                       f"开工安排：{task.name} 目标数量 {before} → {item.target_quantity} {task.unit}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    from app.services.cache import cache_clear
    cache_clear("dashboard:")
    return {"updated": len(data.items), "tasks": [_task_dict(tasks[item.id]) for item in data.items]}




# Retired T22 submission route; only the unified document service writes evidence.


# ===== Check items =====

class CheckItemUpdate(BaseModel):
    is_applicable: Optional[bool] = None
    not_applicable_reason: Optional[str] = None
    is_done: Optional[bool] = None
    failed: Optional[bool] = None
    failed_reason: Optional[str] = None
    version: Optional[int] = None  # 乐观锁版本号（现场多端同时打勾）


def _apply_check(project_id,cid,data,user,db):
    p = ensure_project_visible(db, project_id, user)
    from app.services.project_lifecycle import ensure_project_writable
    from app.services.record_lock import lock_writable_project
    lock_writable_project(db, p, user)
    db.refresh(user)
    from app.services.system_permissions import has_permission
    if not user.is_active or not has_permission(user, "worker.report", default=True):
        raise HTTPException(403, "检查登记权限已变化")
    ci = db.get(CheckItem, cid, populate_existing=True)
    if ci is None or ci.project_id not in (None, project_id) or db.get(Task, ci.task_id).project_id != project_id:
        raise HTTPException(status_code=404, detail="检查项不存在")
    from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
    if p.status not in EXECUTION_PROJECT_STATUSES:
        raise HTTPException(400, '现场实施之前或项目结束后，不能登记检查项')
    from app.services.work_items import phase_of
    from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES
    phase=phase_of(db,db.get(Task,ci.task_id))
    if phase is None or phase.name in REMINDER_ONLY_PHASE_NAMES:raise HTTPException(400,'历史准备检查来源只读，资料要求请到清单维护')
    if ci.vehicle_unit_id:
        from app.models import VehicleUnit
        unit=db.get(VehicleUnit,ci.vehicle_unit_id)
        if unit is None or unit.project_id!=project_id:
            raise HTTPException(404, "检查项车辆不属于当前项目")
        from app.services.vehicle_progress import WRITE_STATUSES
        if p.status not in WRITE_STATUSES:
            raise HTTPException(400, "现场实施之前或项目结束后，不能登记逐车检查")
        task = db.get(Task, ci.task_id, populate_existing=True)
        if data.version is None:
            raise HTTPException(400, "逐车检查须提交当前版本号")
        from app.services.vehicle_checks import ensure_check_mapping
        ensure_check_mapping(db,ci,task)
    if data.is_done is None and data.failed is None and data.is_applicable is None:
        raise HTTPException(status_code=400, detail="请选择检查项状态")
    from app.services.optimistic import bump_version
    if data.version is None:raise HTTPException(400,'检查登记须提交当前版本号')
    bump_version(ci, data.version)  # 现场多端并发打勾：版本不符 409，防互相覆盖

    # 三态（优化-1）：通过 is_done / 不通过 failed（必填原因）/ 不适用 is_applicable=False
    if data.is_done is not None or data.failed is not None or data.is_applicable is not None:
        from app.services.permissions import authorize_project, C_PLAN
        from app.services.permissions import project_capabilities
        member=user.id in (p.members or []) or user.id in (p.manager,p.technical_manager)
        if not member and C_PLAN not in project_capabilities(user,p):
            raise HTTPException(status_code=403,detail='仅有检查登记权限的当前项目成员可操作')
        if data.failed is True and not (data.failed_reason or "").strip():
            raise HTTPException(status_code=400, detail="设为不通过时必须填写原因")
        if ((data.failed is True and data.is_done is True)
                or (data.is_applicable is False and (data.failed is True or data.is_done is True))):
            raise HTTPException(status_code=400, detail="检查项不能同时设为通过、不通过或不适用")
        # Selecting pass/fail after N/A is a real check, not an ignored result.
        if (data.failed is True or data.is_done is True) and not ci.is_applicable:
            data.is_applicable = True
        # 不适用（worker 可设，安全项禁止，必填原因）
        if data.is_applicable is not None:
            if data.is_applicable is False and ci.is_safety_critical:
                raise HTTPException(status_code=400, detail="安全关键检查项禁止设为不适用")
            if data.is_applicable is False and not (data.not_applicable_reason or "").strip():
                raise HTTPException(status_code=400, detail="设为不适用时必须填写原因")
            if (ci.is_applicable != data.is_applicable
                    or (data.is_applicable is False and ci.not_applicable_reason != data.not_applicable_reason)):
                ci.is_applicable = data.is_applicable
                ci.is_done = False
                ci.failed = False
                ci.failed_reason = ""
                ci.done_by = None
                ci.done_at = None
                if data.is_applicable:
                    ci.not_applicable_reason = ""
                    ci.not_applicable_set_by = None
                    ci.not_applicable_set_at = None
                else:
                    ci.not_applicable_reason = data.not_applicable_reason
                    ci.not_applicable_set_by = user.id
                    ci.not_applicable_set_at = utcnow()
                db.flush()
                log_change(db, project_id, "task", cid, "update", user.id,
                           f"检查项「{ci.name}」{'设为不适用：' + (data.not_applicable_reason or '') if not ci.is_applicable else '恢复适用'}（{user.display_name}）")
        if data.failed is True:
            # 不通过：清掉通过状态，记录原因
            ci.is_done = False
            ci.done_by = None
            ci.done_at = None
            ci.failed = True
            ci.failed_reason = data.failed_reason
            db.flush()
            log_change(db, project_id, "task", cid, "update", user.id,
                       f"检查项「{ci.name}」不通过：{data.failed_reason}（{user.display_name}）")
        elif data.failed is False:
            was_failed, old_reason = ci.failed, ci.failed_reason
            ci.failed = False
            ci.failed_reason = ""
            if was_failed:
                log_change(db, project_id, "task", cid, "update", user.id,
                           f"检查项「{ci.name}」取消不通过：{user.display_name}",
                           old_value={"failed": True, "failed_reason": old_reason},
                           new_value={"failed": False, "failed_reason": ""})
        if data.is_done is not None and data.failed is not True:
            old_done, old_failed = ci.is_done, ci.failed
            ci.is_done = data.is_done
            ci.failed = False
            ci.failed_reason = ""
            if data.is_done:
                # Repeating an already-passed checkbox is not a fresh inspection
                # and must not silently replace its original inspector/time.
                if not old_done or old_failed:
                    ci.done_by = user.id
                    ci.done_at = utcnow()
            else:
                ci.done_by = None
                ci.done_at = None
            db.flush()
            if old_done != ci.is_done or old_failed != ci.failed:
                action = "通过" if ci.is_done else "取消不通过" if old_failed else "取消通过"
                log_change(db, project_id, "task", cid, "update", user.id,
                           f"检查项「{ci.name}」{action}：{user.display_name}")
        db.flush()
        return {
            "id": ci.id,
            "is_done": ci.is_done,
            "failed": ci.failed,
            "failed_reason": ci.failed_reason,
            "done_by": ci.done_by,
            "is_applicable": ci.is_applicable,
            "not_applicable_reason": ci.not_applicable_reason,
            "version": ci.version or 0,
        }



@router.put("/projects/{project_id}/check-items/{cid}")
@route_permission('worker.report')
def update_check_item(project_id:str,cid:str,data:CheckItemUpdate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.field_operations import direct_check
    return direct_check(db,project_id,cid,user,data)


# ===== 项目任务参考文档下载（生成时从模板任务复制，任务 JSON 自包含） =====

@router.get("/projects/{project_id}/tasks/{task_id}/reference-docs/{idx}/download")
@route_permission('project.read')
def download_task_reference_doc(project_id: str, task_id: str, idx: int,
                                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.scope import ensure_project_visible
    from starlette.responses import FileResponse
    from app.config import UPLOAD_DIR
    ensure_project_visible(db, project_id, user)
    t = db.query(Task).filter(Task.id == task_id, Task.project_id == project_id).first()
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    docs = t.reference_docs or []
    if idx < 0 or idx >= len(docs):
        raise HTTPException(status_code=404, detail="参考文档不存在")
    d = docs[idx]
    path = UPLOAD_DIR / (d.get("stored_name") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="参考文档文件已丢失")
    return FileResponse(path=str(path), filename=d.get("filename", "doc"),
                        media_type=d.get("content_type") or "application/octet-stream")
