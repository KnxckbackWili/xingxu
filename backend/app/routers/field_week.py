"""The field week: explicit actual facts, authenticated personal history."""
from datetime import date
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query,Response
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models import User,FieldOperation
from app.services.system_permissions import route_permission,route_permission_contextual,has_permission
from app.services.scope import visible_projects,ensure_project_visible
from app.services import field_operations as service


def private(response:Response):response.headers['Cache-Control']='private, no-store'
router=APIRouter(tags=['现场本周'],dependencies=[Depends(private)])


class FieldChange(BaseModel):
    model_config={'extra':'forbid'}
    project_id:str
    kind:Literal['work','vehicle','check']
    target_id:str
    step_key:str=Field(default='',max_length=80)
    weekly_cell_id:str|None=None
    assisted_user_id:str|None=None
    is_done:bool
    completion_date:date
    reason:str=Field(min_length=1,max_length=4000)
    note:str=Field(default='',max_length=4000)
    version:int=Field(strict=True,ge=0)
    client_uuid:str=Field(min_length=8,max_length=64)
    failed:bool|None=None
    failed_reason:str|None=Field(default=None,max_length=4000)
    is_applicable:bool|None=None
    not_applicable_reason:str|None=Field(default=None,max_length=4000)


class Revision(BaseModel):
    model_config={'extra':'forbid'}
    version:int=Field(strict=True,ge=0)
    completion_date:date
    reason:str=Field(min_length=1,max_length=4000)
    note:str=Field(default='',max_length=4000)
    client_uuid:str=Field(min_length=8,max_length=64)


@router.post('/worker/operations')
@route_permission('worker.report')
def record(body:FieldChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    row=service.apply(db,body.project_id,user,body.model_dump(exclude_none=True));db.commit()
    return service.serialize(db,row,user)


@router.put('/worker/records/{record_id}')
@route_permission('worker.report')
def edit(record_id:str,body:Revision,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return revise(db,user,record_id,body)


@router.delete('/worker/records/{record_id}')
@route_permission('worker.report')
def retract(record_id:str,body:Revision,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return revise(db,user,record_id,body,retract=True)


def revise(db,user,record_id,body,*,retract=False):
    old=db.get(FieldOperation,record_id)
    if not old or old.actor_id!=user.id:raise HTTPException(404,'本人记录不存在')
    ensure_project_visible(db,old.project_id,user)
    data={**body.model_dump(),'kind':old.kind,'target_id':old.target_id,'step_key':old.step_key,
          'weekly_cell_id':old.weekly_cell_id,'assisted_user_id':old.assisted_user_id,'is_done':old.is_done}
    row=service.apply(db,old.project_id,user,data,record_id=record_id,retract=retract);db.commit()
    return service.serialize(db,row,user)


@router.get('/worker/records')
@route_permission('personal.records.read')
def records(week_start:date|None=None,project_id:str|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if not has_permission(user,'personal.records.read',default=True):raise HTTPException(403,'没有本人记录查看权限')
    projects=visible_projects(db,user)
    if project_id:
        ensure_project_visible(db,project_id,user);projects=[p for p in projects if p.id==project_id]
    ids=[p.id for p in projects]
    query=db.query(FieldOperation).filter(FieldOperation.project_id.in_(ids),FieldOperation.actor_id==user.id)
    if week_start:
        from datetime import timedelta
        start=week_start-timedelta(days=week_start.weekday());query=query.filter(FieldOperation.completion_date>=start,FieldOperation.completion_date<=start+timedelta(days=6))
    rows=query.order_by(FieldOperation.completion_date.desc(),FieldOperation.project_id,FieldOperation.sequence.desc()).limit(500).all()
    filters={p.id:service.text_redactor(db,p,user) for p in projects}
    return {'records':[service.serialize(db,row,user,text_filter=filters[row.project_id]) for row in rows],'windows':{p.id:service.date_window(p) for p in projects},'truncated':len(rows)==500}


@router.get('/worker/week')
@route_permission('project.read')
def week(week_start:date|None=None,project_id:str|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.field_week import week_view
    return week_view(db,user,week_start=week_start,project_id=project_id)


@router.get('/people/weeks')
@route_permission_contextual('workspace.view','personal.schedule.read',reason='mine仅核对本人周计划权限；team独立核对工作台权限和可见项目范围')
def people(week_start:date|None=None,weeks:int=Query(default=4,ge=1,le=12),scope:Literal['mine','team']='team',user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.field_week import people_view
    return people_view(db,user,week_start=week_start,weeks=weeks,scope=scope)


@router.get('/worker/week-report')
@route_permission('personal.records.read')
def personal_week_report(week_start:date|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.field_week import personal_report
    return personal_report(db,user,week_start=week_start)
