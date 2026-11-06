"""Read projections for field work and the personnel-by-week matrix."""
from datetime import date,timedelta
from sqlalchemy import or_
from fastapi import HTTPException
from app.models import User,Task,Project,Issue,FieldOperation,ProjectDocument
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
    # 所有账号都能记录时，本周已发布的工作都列在“要做的工作”里，不分认领、协助。
    from app.services.open_access import enabled as open_access_enabled
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
            if open_access_enabled() or user.id in (cell.assignee_ids or []):planned.append(row)
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
    issue_scope=Issue.project_id.in_(by_id) if open_access_enabled() else or_(Issue.reporter_id==user.id,Issue.assignee_id==user.id)
    issues=db.query(Issue).filter(Issue.project_id.in_(by_id),issue_scope,
        Issue.status.notin_(('closed','cancelled'))).order_by(Issue.created_at.desc()).limit(100).all()
    return {'state':'unavailable' if any('尚未就绪' in w['message'] for w in warnings) else 'ready','plans':planned,
        'unassigned':unassigned,'assistable':assistable,'vehicle_matrices':matrices,'this_week_documents':documents,
        'my_issues':[{'id':i.id,'project_id':i.project_id,'project_name':by_id[i.project_id].name,'title':i.title,'status':i.status,
            'severity':i.severity,'reporter_id':i.reporter_id,'assignee_id':i.assignee_id} for i in issues],
        'windows':windows,'warnings':warnings,'permissions':{'record':has_permission(user,'worker.report',default=True),
            'upload':has_permission(user,'worker.deliver',default=True),'issues':has_permission(user,'worker.issues',default=True),'plan_read':can_read_plan}}


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
