"""Read projections for field work and the personnel-by-week matrix."""
from datetime import timedelta
from fastapi import HTTPException
from app.models import Task,Issue,FieldOperation,ProjectDocument
from app.services.scope import visible_projects,ensure_project_visible
from app.services.system_permissions import has_permission
from app.services.field_operations import date_window,serialize
from app.time_utils import project_today


def monday(day):return day-timedelta(days=day.weekday())


def plan_cells(db,projects,start,weeks):
    """T40 owns persistence/selection; no fallback to old daily schedules."""
    from app.services.weekly_plans import select_cells
    return select_cells(db,[p.id for p in projects],start,weeks)


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
    by_id={p.id:p for p in projects}
    planned=[];matrices={};windows={}
    # 本周计划的工作都列在“要做的工作”里，谁做完谁登记。
    can_read_plan=has_permission(user,'personal.schedule.read')
    for project in projects:
        start=monday(week_start or project_today(project.timezone));windows[project.id]=date_window(project)
        if not can_read_plan:continue
        cells=plan_cells(db,[project],start,1)
        cache={}
        for cell in cells:
            work=_work(db,cell.task_id)
            if not work:continue
            from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
            row={**cell_dict(db,cell,project,user,cache=cache),'work_item':work,'date_window':windows[project.id],
                 'can_record':has_permission(user,'worker.report') and project.status in EXECUTION_PROJECT_STATUSES}
            planned.append(row)
        from app.services.vehicle_progress import matrix
        matrices[project.id]=matrix(db,project.id)
    from app.services.workbench import project_facts
    facts=project_facts(db,projects,user)
    documents=[item for facts in facts.values() for item in facts['document_attention']['this_week']]
    for item in documents:
        rule=db.get(ProjectDocument,item['document_id']);item['timing_event']=rule.timing_event if rule else None
    issues=db.query(Issue).filter(Issue.project_id.in_(by_id),
        Issue.status.notin_(('closed','cancelled'))).order_by(Issue.created_at.desc()).limit(100).all()
    return {'state':'ready','plans':planned,
        'vehicle_matrices':matrices,'this_week_documents':documents,
        'my_issues':[{'id':i.id,'project_id':i.project_id,'project_name':by_id[i.project_id].name,'title':i.title,'status':i.status,
            'severity':i.severity,'reporter_id':i.reporter_id} for i in issues],
        'windows':windows,'permissions':{'record':has_permission(user,'worker.report'),
            'upload':has_permission(user,'worker.deliver'),'issues':has_permission(user,'worker.issues'),'plan_read':can_read_plan}}


def personal_report(db,user,*,week_start=None):
    if not has_permission(user,'personal.records.read'):raise HTTPException(403,'没有本人记录查看权限')
    from app.services.field_operations import effective_records,text_redactor
    projects=visible_projects(db,user);rows=[];current=[];periods=[]
    for project in projects:
        start=monday(week_start or project_today(project.timezone));end=start+timedelta(days=6)
        periods.append({'project_id':project.id,'timezone':project.timezone,'start':start.isoformat(),'end':end.isoformat()})
        all_records=db.query(FieldOperation).filter_by(project_id=project.id,actor_id=user.id).order_by(FieldOperation.sequence).all()
        redact=text_redactor(db,project,user)
        rows.extend(serialize(db,row,user,text_filter=redact) for row in all_records if start<=row.completion_date<=end)
        current.extend(row for row in effective_records(all_records) if start<=row.completion_date<=end)
    return {'periods':periods,'records':rows,'summary':{'actual_records':len(current),'completed':sum(r.is_done for r in current)},'generated_from':'actual_field_operations'}
