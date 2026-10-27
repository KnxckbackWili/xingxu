"""Vehicle progress matrix; lifecycle problem history remains a separate API."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import User, VehicleUnit, VehicleProgress, VehicleStep, VehicleProgressMigration, Template
from app.services.system_permissions import route_permission, has_permission
from app.services.scope import ensure_project_visible
from app.services.permissions import C_PLAN, project_capabilities
from app.services.record_lock import lock_writable_project
from app.services.change_log import log_change
from app.services import vehicle_progress as service
from app.time_utils import project_today, utcnow

router=APIRouter(tags=['车辆进度表'])


class StepDefinition(BaseModel):
    model_config={'extra':'forbid'}
    key:str=Field(min_length=1,max_length=80,pattern=r'^[a-z][a-z0-9_]*$')
    name:str=Field(min_length=1,max_length=200)


class StepList(BaseModel):
    model_config={'extra':'forbid'}
    steps:list[StepDefinition]=Field(min_length=1,max_length=30)


@router.get('/templates/{template_id}/vehicle-steps')
@route_permission('system.templates.read')
def list_steps(template_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if template_id!='default' and db.get(Template,template_id) is None:
        raise HTTPException(404,'模板不存在')
    rows=service.template_steps(db,template_id)
    return [{'key':r.key,'name':r.name} for r in rows] or [{'key':k,'name':n} for k,n in service.DEFAULT_STEPS]


@router.put('/templates/{template_id}/vehicle-steps')
@route_permission('system.templates.manage')
def save_steps(template_id:str,body:StepList,user:User=Depends(require_admin),db:Session=Depends(get_db)):
    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db,template_id)
    recheck_authority(db,user.id)
    if template_id!='default' and db.get(Template,template_id) is None:
        raise HTTPException(404,'模板不存在')
    keys=[r.key for r in body.steps]
    if len(keys)!=len(set(keys)) or any(not r.name.strip() for r in body.steps):
        raise HTTPException(400,'环节标识不能重复，名称不能为空')
    from app.models import Task
    tid = None if template_id == 'default' else template_id
    linked = db.query(Task).filter(Task.project_id.is_(None), Task.template_id == tid,
        Task.vehicle_step_key.isnot(None), Task.vehicle_step_key.notin_(keys)).first()
    if linked:
        raise HTTPException(400, '仍有工作关联待删除环节，请先调整工作关联')
    old=[{'key':r.key,'name':r.name} for r in service.template_steps(db,template_id)]
    db.query(VehicleStep).filter_by(template_id=template_id).delete()
    for i,row in enumerate(body.steps):
        db.add(VehicleStep(template_id=template_id,key=row.key,name=row.name.strip(),sort_order=i))
    new=[r.model_dump() for r in body.steps]
    log_change(db,None,'vehicle_steps',template_id,'update',user.id,'修改模板车辆环节（已有项目快照不变）',old,new)
    db.commit()
    return new


@router.get('/projects/{project_id}/vehicle-progress')
@route_permission('project.read')
def get_matrix(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=ensure_project_visible(db,project_id,user)
    result=service.matrix(db,project_id)
    result['source_snapshot_available']=project.portable_unverified_snapshot is not None
    result['today']=project_today(project.timezone).isoformat()
    result['can_manage']=C_PLAN in project_capabilities(user,project)
    result['can_record']=_has_record_authority(db,project,user) and project.status in service.WRITE_STATUSES
    return result


def _has_record_authority(db,project,user):
    return has_permission(user,'worker.report',default=True) and user.role!='readonly' and (
        C_PLAN in project_capabilities(user,project) or user.id in (project.members or [])
        or user.id in (project.manager,project.technical_manager))


class CellChange(BaseModel):
    model_config={'extra':'forbid'}
    vehicle_unit_id:str
    step_key:str=Field(min_length=1,max_length=80)
    version:int=Field(ge=0)


class MatrixChange(BaseModel):
    model_config={'extra':'forbid'}
    cells:list[CellChange]=Field(min_length=1,max_length=500)
    is_done:bool
    done_on:date|None=None
    reason:str=Field(default='',max_length=1000)
    note:str=Field(default='',max_length=1000)
    claim_migrated:bool=False


def _apply_matrix(project_id,body,user,db):
    project=ensure_project_visible(db,project_id,user)
    if not _has_record_authority(db,project,user):
        raise HTTPException(403,'只有有填报权限的项目成员可以登记车辆环节')
    project=lock_writable_project(db,project,user)
    db.refresh(user)
    if not _has_record_authority(db,project,user):
        raise HTTPException(403,'车辆环节登记权限已变化')
    if project.status not in service.WRITE_STATUSES:
        raise HTTPException(400,'现场实施之前或项目结束后，不能勾选车辆进度表')
    if not body.is_done and not body.reason.strip():
        raise HTTPException(400,'取消勾选必须填写理由')
    if body.claim_migrated and not body.is_done:
        raise HTTPException(400,'只能将历史凭证补录为已完成环节')
    if body.is_done and not body.claim_migrated and body.done_on is None:
        raise HTTPException(400,'请填写实际完成日期')
    if body.done_on and body.done_on>project_today(project.timezone):
        raise HTTPException(400,'完成日期不能晚于项目当地今天')
    pairs=[(r.vehicle_unit_id,r.step_key) for r in body.cells]
    if len(pairs)!=len(set(pairs)):
        raise HTTPException(400,'批量列表中包含重复单元格')
    steps={r.key:r for r in service.project_steps(db,project_id)}
    units={r.id:r for r in db.query(VehicleUnit).filter(VehicleUnit.project_id==project_id,VehicleUnit.id.in_([r.vehicle_unit_id for r in body.cells])).all()}
    facts={(r.vehicle_unit_id,r.step_key):r for r in db.query(VehicleProgress).filter_by(project_id=project_id).all()}
    credits={r.step_key:r for r in db.query(VehicleProgressMigration).filter_by(project_id=project_id).all()}
    needed={}
    for cell in body.cells:
        if cell.vehicle_unit_id not in units or cell.step_key not in steps:
            raise HTTPException(404,'车辆或环节不属于当前项目')
        fact=facts.get((cell.vehicle_unit_id,cell.step_key))
        if (fact.version if fact else 0)!=cell.version:
            raise HTTPException(409,'车辆进度已更新，请刷新后核对原操作')
        if body.claim_migrated and (not fact or not fact.is_done):
            needed[cell.step_key]=needed.get(cell.step_key,0)+1
    for key,count in needed.items():
        if key not in credits or credits[key].unassigned_count<count:
            raise HTTPException(400,'历史未知车号凭证不足，请刷新后核对')
    for key,step in steps.items():
        if step.expected_quantity is None:
            continue
        current=sum(1 for f in facts.values() if f.step_key==key and f.is_done)+(credits[key].unassigned_count if key in credits else 0)
        delta=sum((1 if body.is_done else -1) for c in body.cells if c.step_key==key
                  and bool(facts.get((c.vehicle_unit_id,key)) and facts[(c.vehicle_unit_id,key)].is_done)!=body.is_done)
        if body.claim_migrated: delta=0
        if not body.is_done:
            delta+=sum(1 for c in body.cells if c.step_key==key and (f:=facts.get((c.vehicle_unit_id,key))) and f.is_done and f.migrated)
        if current+delta>step.expected_quantity:
            raise HTTPException(400,'该历史环节已有完成凭证，请用“补录迁移车号”转移凭证，不能重复计算')
    if body.is_done:
        from app.services.vehicle_checks import completion_blockers
        blockers = completion_blockers(db, project_id, body.cells)
        if blockers:
            raise HTTPException(400, {'message': '车辆检查未满足，不能完成环节', 'blockers': blockers})
    # Validate every cell before changing anything: a batch is one transaction.
    for cell in body.cells:
        pair=(cell.vehicle_unit_id,cell.step_key)
        fact=facts.get(pair)
        if fact and fact.is_done==body.is_done:
            if body.is_done and (body.claim_migrated or (fact.done_on==body.done_on and (fact.note or '')==body.note.strip())):
                continue
            if not body.is_done:
                continue
        old={'is_done':fact.is_done,'done_on':str(fact.done_on) if fact.done_on else None,'migrated':fact.migrated,'version':fact.version} if fact else None
        if fact is None:
            fact=VehicleProgress(project_id=project_id,vehicle_unit_id=cell.vehicle_unit_id,step_key=cell.step_key,version=0)
            db.add(fact)
        was_done=bool(fact.is_done) if old else False
        was_migrated=bool(fact.migrated) if old else False
        if not body.is_done and was_done and was_migrated:
            credits[cell.step_key].unassigned_count+=1
        if body.is_done and not was_done and body.claim_migrated:
            credits[cell.step_key].unassigned_count-=1
        fact.is_done=body.is_done
        fact.migrated=body.claim_migrated if body.is_done and not was_done else was_migrated
        fact.done_on=body.done_on if body.is_done else None
        fact.done_by=user.id
        fact.recorded_at=utcnow()
        fact.note=body.note.strip() if body.is_done else body.reason.strip()
        fact.version+=1
        db.flush()
        log_change(db,project_id,'vehicle_progress',fact.id,'complete' if body.is_done else 'reopen',user.id,
            f"{units[cell.vehicle_unit_id].asset_code} · {steps[cell.step_key].name}：{'补录迁移凭证' if body.claim_migrated else '勾选' if body.is_done else '取消'} {body.reason.strip()}",old,
            {'is_done':fact.is_done,'done_on':str(fact.done_on) if fact.done_on else None,'migrated':fact.migrated,'version':fact.version})
    db.flush()
    for unit in units.values(): service.derive_stage(db,unit)
    return service.matrix(db,project_id)


@router.put('/projects/{project_id}/vehicle-progress')
@route_permission('worker.report')
def change_matrix(project_id:str,body:MatrixChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.field_operations import direct_matrix
    return direct_matrix(db,project_id,user,body)


class HistoricalTarget(BaseModel):
    model_config={'extra':'forbid'}
    expected_quantity:int=Field(ge=0,le=100000)
    previous_quantity:int|None
    reason:str=Field(min_length=1,max_length=1000)


@router.put('/projects/{project_id}/vehicle-progress/steps/{step_key}')
@route_permission('project.manage_plan')
def clarify_historical_target(project_id:str,step_key:str,body:HistoricalTarget,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.models import ProjectVehicleStep
    from app.services.permissions import authorize_project
    project=ensure_project_visible(db,project_id,user)
    authorize_project(user,project,C_PLAN)
    project=lock_writable_project(db,project,user)
    db.refresh(user)
    if not user.is_active:raise HTTPException(401,"账号已停用，请重新登录")
    authorize_project(user,project,C_PLAN)
    if project.status not in service.WRITE_STATUSES:
        raise HTTPException(400,'现场实施之前或项目结束后，不能修改车辆进度表')
    step=db.query(ProjectVehicleStep).filter_by(project_id=project_id,key=step_key).first()
    if step is None:raise HTTPException(404,'车辆环节不存在')
    credit=db.query(VehicleProgressMigration).filter_by(project_id=project_id,step_key=step_key).first()
    unverified=(project.portable_unverified_snapshot or {}).get('vehicle_progress_matrix') or {}
    source_step=next((s for s in unverified.get('steps',[]) if s.get('key')==step_key and s.get('source_task_id')),None)
    source_credit=next((s for s in unverified.get('legacy',[]) if s.get('step_key')==step_key),None)
    if credit is None and step.source_task_id is None and source_step is None and source_credit is None:raise HTTPException(400,'仅历史来源环节可核对应完成台数；新环节按车型配置计算')
    if not body.reason.strip():raise HTTPException(400,'核对应完成台数须填写理由')
    known=sum(1 for r in db.query(VehicleProgress).filter_by(project_id=project_id,step_key=step_key,is_done=True)) + (credit.unassigned_count if credit else 0)
    if body.expected_quantity<known:raise HTTPException(400,'应完成台数不能少于已有完成凭证')
    old=step.expected_quantity
    if old!=body.previous_quantity:raise HTTPException(409,'环节应完成台数已变化，请刷新核对')
    step.expected_quantity=body.expected_quantity
    log_change(db,project_id,'project_vehicle_step',step.id,'clarify_target',user.id,
        f'核对历史环节应完成台数：{step.name}；{body.reason.strip()}',{'expected_quantity':old},{'expected_quantity':body.expected_quantity})
    db.commit()
    return service.matrix(db,project_id)


@router.get('/projects/{project_id}/vehicle-progress/source')
@route_permission('project.read')
def read_portable_source(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=ensure_project_visible(db,project_id,user)
    return {'read_only':True,'verified':False,'source':project.portable_unverified_snapshot}


@router.get('/projects/{project_id}/vehicle-units/{unit_id}/checks')
@route_permission('project.read')
def get_vehicle_checks(project_id:str,unit_id:str,step_key:str|None=None,
                       user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.vehicle_checks import checks_for_unit
    project=ensure_project_visible(db,project_id,user)
    if step_key and step_key not in {s.key for s in service.project_steps(db,project_id)}:
        raise HTTPException(404,'环节不属于当前项目')
    return {'items':checks_for_unit(db,project_id,unit_id,step_key),
            'can_record':has_permission(user,'worker.report',default=True) and (C_PLAN in project_capabilities(user,project) or user.role=='worker' and user.id in (project.members or [])) and project.status in service.WRITE_STATUSES}


class GenerateChecks(BaseModel):
    model_config={'extra':'forbid'}
    vehicle_unit_ids:list[str]=Field(min_length=1,max_length=500)
    reason:str=Field(min_length=1,max_length=1000)


@router.post('/projects/{project_id}/tasks/{task_id}/vehicle-checks/generate')
@route_permission('project.manage_plan')
def generate_vehicle_checks(project_id:str,task_id:str,body:GenerateChecks,
                            user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.models import Task, CheckItem
    from app.services.permissions import authorize_project
    from app.services.vehicle_checks import snapshot_definitions,generate_for_units
    project=ensure_project_visible(db,project_id,user)
    project=lock_writable_project(db,project,user)
    db.refresh(user)
    if not has_permission(user,"project.manage_plan",default=True):
        raise HTTPException(403,"工作计划维护权限已变化")
    authorize_project(user,project,C_PLAN)
    if project.status in {'completed','archived'}:
        raise HTTPException(400,'已结束项目不能新增复核检查')
    if not body.reason.strip():raise HTTPException(400,'为既有车辆生成复核须说明理由')
    task=db.get(Task,task_id,populate_existing=True)
    if task is None or task.project_id!=project_id or task.quantity_type!='per_vehicle':
        raise HTTPException(404,'按车工作不存在')
    if not task.vehicle_step_key:raise HTTPException(400,'请先明确关联本项目车辆环节')
    ids=set(body.vehicle_unit_ids)
    units=db.query(VehicleUnit).filter(VehicleUnit.project_id==project_id,VehicleUnit.id.in_(ids)).all()
    if len(ids)!=len(units):raise HTTPException(404,'车辆不属于当前项目')
    from sqlalchemy import or_
    source=db.query(CheckItem).filter_by(task_id=task.id,vehicle_unit_id=None).filter(or_(CheckItem.project_id==project_id,CheckItem.project_id.is_(None))).all()
    snapshot_definitions(db,task,source)
    rows=generate_for_units(db,project_id,units,task)
    log_change(db,project_id,'vehicle_check',task.id,'generate_review',user.id,
        f'明确为既有实车生成{len(rows)}项待复核检查；{body.reason.strip()}',
        None,{'vehicle_unit_ids':sorted(ids),'check_ids':[r.id for r in rows]})
    db.commit()
    return {'created':len(rows),'check_ids':[r.id for r in rows]}
