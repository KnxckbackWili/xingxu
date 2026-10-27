"""Read projections for field work and the personnel-by-week matrix."""
from datetime import date,timedelta
from sqlalchemy import or_
from fastapi import HTTPException
from app.models import User,Task,Project,Issue,FieldOperation,UserUnavailability,ProjectDocument
from app.services.scope import visible_projects,ensure_project_visible
from app.services.permissions import project_capabilities,C_PLAN
from app.services.system_permissions import has_permission
from app.services.field_operations import date_window,serialize
from app.time_utils import project_today


def monday(day):return day-timedelta(days=day.weekday())


def plan_cells(db,projects,start,weeks):
    """T40 owns persistence/selection; no fallback to old daily schedules."""
    from app.services.weekly_plans import select_cells
    return select_cells(db,[p.id for p in projects],start,weeks,published_only=True)


def cell_dict(db,cell,project,user,*,cache=None):
    from app.services.weekly_plans import serialize_cell
    return serialize_cell(db,project,cell,user,cache=cache)


def _work(db,task_id):
    from app.services.work_items import item_dict
    task=db.get(Task,task_id)
    return item_dict(db,task,checks=True) if task else None


def week_view(db,user,*,week_start=None,project_id=None):
    projects=visible_projects(db,user)
    if project_id:projects=[ensure_project_visible(db,project_id,user)]
    by_id={p.id:p for p in projects};users={u.id:u for u in db.query(User).filter_by(is_active=True)}
    planned=[];unassigned=[];assistable=[];warnings=[];matrices={};windows={}
    can_read_plan=has_permission(user,'personal.schedule.read',default=True)
    if not can_read_plan:warnings.append({'project_id':'','message':'本人周计划查看权限已关闭'})
    for project in projects:
        start=monday(week_start or project_today(project.timezone));windows[project.id]=date_window(project)
        if not can_read_plan:continue
        cells=plan_cells(db,[project],start,1)
        if cells is None:
            warnings.append({'project_id':project.id,'message':'周计划服务尚未就绪，当前安排未知'});continue
        cache={}
        from app.services.weekly_plans import can_claim,project_warnings
        warnings.extend(project_warnings(db,project,cells,user))
        for cell in cells:
            if not cell.published:continue
            work=_work(db,cell.task_id)
            if not work:continue
            from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
            row={**cell_dict(db,cell,project,user,cache=cache),'work_item':work,'date_window':windows[project.id],
                 'can_record':has_permission(user,'worker.report',default=True) and project.status in EXECUTION_PROJECT_STATUSES and (user.id in set(project.members or [])|{project.manager,project.technical_manager} or C_PLAN in project_capabilities(user,project))}
            if user.id in (cell.assignee_ids or []):planned.append(row)
            elif not cell.assignee_ids and can_claim(project,user):unassigned.append(row)
            else:assistable.append(row)
        from app.services.vehicle_progress import matrix
        matrices[project.id]=matrix(db,project.id)
        from app.services.holidays import calendar_in_range
        holiday=calendar_in_range(start,start+timedelta(days=6),db)
        if holiday['missing_holiday_years']:warnings.append({'project_id':project.id,'message':'缺少年度节假日数据','years':holiday['missing_holiday_years']})
    from app.services.workbench import project_facts
    facts=project_facts(db,projects,user)
    documents=[item for facts in facts.values() for item in facts['document_attention']['this_week']]
    for item in documents:
        rule=db.get(ProjectDocument,item['document_id']);item['timing_event']=rule.timing_event if rule else None
    issues=db.query(Issue).filter(Issue.project_id.in_(by_id),or_(Issue.reporter_id==user.id,Issue.assignee_id==user.id),
        Issue.status.notin_(('closed','cancelled'))).order_by(Issue.created_at.desc()).limit(100).all()
    return {'state':'unavailable' if any('尚未就绪' in w['message'] for w in warnings) else 'ready','plans':planned,
        'unassigned':unassigned,'assistable':assistable,'vehicle_matrices':matrices,'this_week_documents':documents,
        'my_issues':[{'id':i.id,'project_id':i.project_id,'project_name':by_id[i.project_id].name,'title':i.title,'status':i.status,
            'severity':i.severity,'reporter_id':i.reporter_id,'assignee_id':i.assignee_id} for i in issues],
        'windows':windows,'warnings':warnings,'permissions':{'record':has_permission(user,'worker.report',default=True),
            'upload':has_permission(user,'worker.deliver',default=True),'issues':has_permission(user,'worker.issues',default=True),'plan_read':can_read_plan}}


def people_view(db,user,*,week_start=None,weeks=4,scope='team'):
    if scope=='team' and not has_permission(user,'workspace.view'):raise HTTPException(403,'没有团队人员周计划查看权限')
    if scope=='mine' and not has_permission(user,'personal.schedule.read',default=True):raise HTTPException(403,'没有本人周计划查看权限')
    projects=visible_projects(db,user);by_id={p.id:p for p in projects}
    # A global week selector denotes calendar Mondays; each project's local
    # current week is returned separately when no week was selected.
    local_weeks={p.id:monday(project_today(p.timezone)) for p in projects}
    common_start=monday(week_start) if week_start else min(local_weeks.values(),default=monday(date.today()))
    starts={p.id:common_start for p in projects}
    users={u.id:u for u in db.query(User).filter_by(is_active=True)};all_cells=[];warnings=[];metadata=[]
    from app.services.holidays import calendar_in_range
    for p in projects:
        if week_start is None and local_weeks[p.id]!=common_start:
            warnings.append({'project_id':p.id,'message':'项目当地当前周与统一人员表首周不同，请按标注周一日期核对'})
        selected=plan_cells(db,[p],starts[p.id],weeks)
        if selected is None:warnings.append({'project_id':p.id,'message':'周计划尚未读取'});continue
        for cell in selected:
            if cell.published and (scope!='mine' or user.id in (cell.assignee_ids or [])):all_cells.append(cell)
        meta=calendar_in_range(starts[p.id],starts[p.id]+timedelta(days=weeks*7-1),db)
        metadata.append({'project_id':p.id,'timezone':p.timezone,'week_start':starts[p.id].isoformat(),'current_week_start':local_weeks[p.id].isoformat(),**meta})
    people_ids={uid for c in all_cells for uid in c.assignee_ids or []}
    if scope=='mine':people_ids={user.id}
    elif has_permission(user,'system.availability.manage',default=user.role in ('admin','pm')):
        people_ids|={uid for p in projects for uid in (p.members or [])}|{p.manager for p in projects if p.manager}
    task_names={r.id:r.name for r in db.query(Task).filter(Task.id.in_({c.task_id for c in all_cells}))}
    rows=[]
    from app.services.availability import unavailability_for_viewer
    lower=min(starts.values(),default=monday(week_start or date.today()));upper=max((s+timedelta(days=weeks*7-1) for s in starts.values()),default=lower)
    unavailable=db.query(UserUnavailability).filter(UserUnavailability.user_id.in_(people_ids),UserUnavailability.start_date<=upper,UserUnavailability.end_date>=lower).all()
    conflicts=[]
    for uid in sorted(people_ids):
        person=users.get(uid)
        if not person:continue
        assigned=[c for c in all_cells if uid in (c.assignee_ids or [])]
        by_week={}
        for cell in assigned:by_week.setdefault(cell.week_start,set()).add(cell.project_id)
        personal_conflicts=[{'week_start':start.isoformat(),'project_ids':sorted(ids)} for start,ids in sorted(by_week.items()) if len(ids)>1]
        conflicts.extend({'user_id':uid,**item} for item in personal_conflicts)
        rows.append({'id':uid,'name':person.display_name,'role':person.role,
            'cells':[cell_dict(db,c,by_id[c.project_id],user) for c in assigned],
            'unavailable':[unavailability_for_viewer(db,user,r,person.display_name) for r in unavailable if r.user_id==uid],
            'conflicts':personal_conflicts})
    return {'state':'unavailable' if any(w['message']=='周计划尚未读取' for w in warnings) else 'ready','people':rows,'projects':[{'id':p.id,'name':p.name,'timezone':p.timezone} for p in projects],
            'weeks':weeks,'week_start':lower.isoformat(),'calendar':metadata,'conflicts':conflicts,'warnings':warnings,
            'unassigned':[cell_dict(db,c,by_id[c.project_id],user) for c in all_cells if not c.assignee_ids],
            'permissions':{'manage_unavailability':has_permission(user,'system.availability.manage',default=False)}}


def personal_report(db,user,*,week_start=None):
    if not has_permission(user,'personal.records.read',default=True):raise HTTPException(403,'没有本人记录查看权限')
    from app.services.field_operations import effective_records,text_redactor
    projects=visible_projects(db,user);rows=[];current=[];periods=[]
    for project in projects:
        start=monday(week_start or project_today(project.timezone));end=start+timedelta(days=6)
        periods.append({'project_id':project.id,'timezone':project.timezone,'start':start.isoformat(),'end':end.isoformat()})
        all_records=db.query(FieldOperation).filter_by(project_id=project.id,actor_id=user.id).order_by(FieldOperation.sequence).all()
        redact=text_redactor(db,project,user)
        rows.extend(serialize(db,row,user,text_filter=redact) for row in all_records if start<=row.completion_date<=end)
        current.extend(row for row in effective_records(all_records) if start<=row.completion_date<=end)
    return {'periods':periods,'records':rows,'summary':{'actual_records':len(current),'completed':sum(r.is_done for r in current),
        'assisted':sum(bool(r.assisted_user_id) for r in current)},'generated_from':'actual_field_operations'}
