"""Canonical flat work maintenance; legacy module/quantity APIs are sources only."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db import get_db
from app.deps import get_current_user,require_admin
from app.models import Project,Task,Phase,Template,User,CheckItem
from app.services.system_permissions import route_permission,has_permission
from app.services.scope import ensure_project_visible
from app.services.permissions import C_PLAN,project_capabilities
from app.services.change_log import log_change
from app.services import work_items as service
from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES
router=APIRouter(tags=['工作项'])


class CheckDefinition(BaseModel):
    model_config={'extra':'forbid'}
    name:str=Field(min_length=1,max_length=300)
    description:str=Field(default='',max_length=10000)
    is_required:bool=True
    is_safety_critical:bool=False


class WorkCreate(BaseModel):
    model_config={'extra':'forbid'}
    phase_id:str
    kind:Literal['vehicle','other']='other'
    name:str=Field(min_length=1,max_length=200)
    description:str=Field(default='',max_length=20000)
    group_label:str=Field(default='',max_length=200)
    vehicle_step_key:str|None=Field(default=None,max_length=80)
    applicable_vehicle_types:list[str]=Field(default_factory=list,max_length=100)
    scope_conditions:list[Literal['need_wms','need_charging']]=Field(default_factory=list)
    checks:list[CheckDefinition]=Field(default_factory=list,max_length=100)
    sort_order:int|None=Field(default=None,ge=0)


class WorkUpdate(BaseModel):
    model_config={'extra':'forbid'}
    version:int=Field(ge=0)
    phase_id:str|None=None
    name:str|None=Field(default=None,min_length=1,max_length=200)
    description:str|None=Field(default=None,max_length=20000)
    group_label:str|None=Field(default=None,max_length=200)
    vehicle_step_key:str|None=Field(default=None,max_length=80)
    sort_order:int|None=Field(default=None,ge=0)


class TemplateWorkUpdate(WorkUpdate):
    kind:Literal['vehicle','other']|None=None
    applicable_vehicle_types:list[str]|None=Field(default=None,max_length=100)
    scope_conditions:list[str]|None=Field(default=None,max_length=100)
    checks:list[CheckDefinition]|None=Field(default=None,max_length=100)


class FailedCheckVersion(BaseModel):
    model_config={'extra':'forbid'}
    id:str
    version:int=Field(ge=0)


class WorkCompletion(BaseModel):
    model_config={'extra':'forbid'}
    version:int=Field(ge=0)
    is_completed:bool
    reason:str=Field(min_length=1,max_length=4000)
    override_failed:bool=False
    failed_checks:list[FailedCheckVersion]=Field(default_factory=list,max_length=500)


class PhaseCreate(BaseModel):
    model_config={'extra':'forbid'}
    name:str=Field(min_length=1,max_length=100)
    color:str=Field(default='#1890ff',max_length=20)


def _catalog(db,project_id=None,template_id=None):
    tid=None if template_id=='default' else template_id
    tasks=db.query(Task).filter(Task.project_id==project_id)
    if project_id is None:tasks=tasks.filter(Task.template_id==tid)
    by_phase={}
    for task in tasks.order_by(Task.sort_order,Task.id):
        phase=service.phase_of(db,task)
        if phase is None or phase.name in REMINDER_ONLY_PHASE_NAMES:continue
        by_phase.setdefault(phase.id,[]).append(service.item_dict(db,task,checks=True))
    phases=db.query(Phase).filter(Phase.project_id==project_id,Phase.name.notin_(REMINDER_ONLY_PHASE_NAMES))
    if project_id is None:phases=phases.filter(Phase.template_id==tid)
    return [{'id':phase.id,'name':service.stage_label(phase.name),'source_name':phase.name,'color':phase.color,'sort_order':phase.sort_order or 0,
             'work_items':by_phase.get(phase.id,[])} for phase in phases.order_by(Phase.sort_order,Phase.id)]


@router.get('/projects/{project_id}/work-items')
@route_permission('project.read')
def list_project_work(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES,ACTIVE_PROJECT_STATUSES
    project=ensure_project_visible(db,project_id,user)
    caps=project_capabilities(user,project)
    can_plan=C_PLAN in caps and project.status in ACTIVE_PROJECT_STATUSES
    can_record=has_permission(user,'worker.report',default=True) and (C_PLAN in caps or user.id in (project.members or []) or user.id in (project.manager,project.technical_manager)) and project.status in EXECUTION_PROJECT_STATUSES
    legacy=[service.item_dict(db,t,checks=True) for t in db.query(Task).filter_by(project_id=project_id) if (service.phase_of(db,t) is None or service.phase_of(db,t).name in REMINDER_ONLY_PHASE_NAMES)]
    return {'legacy_work_items':legacy,'phases':_catalog(db,project_id=project_id),'permissions':{'plan':can_plan,'record':can_record,'override':C_PLAN in caps},'project_status':project.status}


@router.post('/projects/{project_id}/work-items')
@route_permission('project.manage_plan')
def create_project_work(project_id:str,body:WorkCreate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=service.lock_plan(db,ensure_project_visible(db,project_id,user),user)
    task=Task(project_id=project.id)
    service.set_definition(db,task,body.model_dump(),creating=True)
    log_change(db,project.id,'task',task.id,'create',user.id,f'添加工作项「{task.name}」')
    db.commit();_invalidate();return service.item_dict(db,task,checks=True)


@router.put('/projects/{project_id}/work-items/{task_id}')
@route_permission('project.manage_plan')
def update_project_work(project_id:str,task_id:str,body:WorkUpdate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=service.lock_plan(db,ensure_project_visible(db,project_id,user),user)
    task=service.lock_work(db,project,user,task_id,body.version)
    old=service.item_dict(db,task)
    service.set_definition(db,task,body.model_dump(exclude_unset=True,exclude={'version'}))
    log_change(db,project.id,'task',task.id,'update',user.id,f'修改工作项「{task.name}」',old,service.item_dict(db,task))
    db.commit();_invalidate();return service.item_dict(db,task,checks=True)


@router.put('/projects/{project_id}/work-items/{task_id}/completion')
@route_permission('worker.report')
def complete_project_work(project_id:str,task_id:str,body:WorkCompletion,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=ensure_project_visible(db,project_id,user)
    task=service.complete(db,project,user,task_id,body.model_dump())
    db.commit()
    from app.services.cache import cache_clear
    cache_clear('dashboard:')
    return service.item_dict(db,task,checks=True)


@router.get('/projects/{project_id}/work-items/{task_id}/history')
@route_permission('project.read')
def work_history(project_id:str,task_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    ensure_project_visible(db,project_id,user)
    task=db.get(Task,task_id)
    if task is None or task.project_id!=project_id:raise HTTPException(404,'工作项不存在')
    return service.legacy_quantity(db,task)


@router.post('/projects/{project_id}/work-phases')
@route_permission('project.manage_plan')
def create_project_phase(project_id:str,body:PhaseCreate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=service.lock_plan(db,ensure_project_visible(db,project_id,user),user)
    if body.name.strip() in REMINDER_ONLY_PHASE_NAMES or not body.name.strip():raise HTTPException(400,'请选择有效的实施阶段名')
    phase=Phase(project_id=project.id,name=service.stage_label(body.name.strip()),color=body.color,sort_order=(db.query(func.max(Phase.sort_order)).filter_by(project_id=project.id).scalar() or 0)+1)
    db.add(phase);db.flush();log_change(db,project.id,'phase',phase.id,'create',user.id,f'新增工作阶段「{phase.name}」');db.commit()
    return {'id':phase.id,'name':service.stage_label(phase.name),'source_name':phase.name,'color':phase.color,'work_items':[]}


def _invalidate():
    from app.services.cache import cache_clear
    cache_clear('dashboard:')


def _draft(db,template_id):
    if template_id!='default':db.get(Template,template_id).status='draft'


def _template(db,template_id):
    if template_id!='default' and db.get(Template,template_id) is None:raise HTTPException(404,'模板不存在')


def _lock_template(db,template_id,user):
    from app.services.document_requirements import lock_templates,recheck_authority
    _template(db,template_id);lock_templates(db,template_id);recheck_authority(db,user.id)


@router.get('/templates/{template_id}/work-items')
@route_permission('system.templates.read')
def list_template_work(template_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    _template(db,template_id)
    return {'phases':_catalog(db,template_id=template_id)}


@router.post('/templates/{template_id}/work-items')
@route_permission('system.templates.manage')
def create_template_work(template_id:str,body:WorkCreate,user:User=Depends(require_admin),db:Session=Depends(get_db)):
    _lock_template(db,template_id,user)
    task=Task(template_id=None if template_id=='default' else template_id)
    service.set_definition(db,task,body.model_dump(),creating=True)
    _draft(db,template_id)
    log_change(db,None,'template_task',task.id,'create',user.id,f'新增模板工作项「{task.name}」');db.commit()
    return service.item_dict(db,task,checks=True)


@router.put('/templates/{template_id}/work-items/{task_id}')
@route_permission('system.templates.manage')
def update_template_work(template_id:str,task_id:str,body:TemplateWorkUpdate,user:User=Depends(require_admin),db:Session=Depends(get_db)):
    _lock_template(db,template_id,user)
    task=db.get(Task,task_id)
    if task is None or task.project_id or task.template_id!=(None if template_id=='default' else template_id):raise HTTPException(404,'模板工作项不存在')
    from app.services.optimistic import bump_version
    bump_version(task,body.version)
    old=service.item_dict(db,task,checks=True)
    values=body.model_dump(exclude_unset=True,exclude={'version'})
    if values.get('kind'):
        if values['kind']=='vehicle' and task.quantity_type!='per_vehicle' and not values.get('vehicle_step_key'):raise HTTPException(400,'改为车辆工作必须明确关联真实环节')
        task.quantity_type='per_vehicle' if values['kind']=='vehicle' else 'fixed'
        if values['kind']=='other':values['vehicle_step_key']=None
    service.set_definition(db,task,values)
    if 'checks' in body.model_fields_set:
        db.query(CheckItem).filter_by(task_id=task.id,project_id=None).delete(synchronize_session=False)
        for index,definition in enumerate(body.checks or []):
            db.add(CheckItem(task_id=task.id,template_id=task.template_id,name=definition.name,description=definition.description,
                is_required=definition.is_required,is_safety_critical=definition.is_safety_critical,sort_order=index))
        db.flush()
    _draft(db,template_id)
    log_change(db,None,'template_task',task.id,'update',user.id,f'修改模板工作项「{task.name}」',old,service.item_dict(db,task));db.commit()
    return service.item_dict(db,task,checks=True)


@router.post('/templates/{template_id}/work-phases')
@route_permission('system.templates.manage')
def create_template_phase(template_id:str,body:PhaseCreate,user:User=Depends(require_admin),db:Session=Depends(get_db)):
    _lock_template(db,template_id,user)
    if not body.name.strip() or body.name.strip() in REMINDER_ONLY_PHASE_NAMES:raise HTTPException(400,'请选择有效的实施阶段名')
    tid=None if template_id=='default' else template_id
    phase=Phase(template_id=tid,name=service.stage_label(body.name.strip()),color=body.color,sort_order=(db.query(func.max(Phase.sort_order)).filter_by(project_id=None,template_id=tid).scalar() or 0)+1)
    _draft(db,template_id)
    db.add(phase);db.flush();log_change(db,None,'template_phase',phase.id,'create',user.id,f'新增模板工作阶段「{phase.name}」');db.commit()
    return {'id':phase.id,'name':service.stage_label(phase.name),'source_name':phase.name,'color':phase.color,'work_items':[]}
