"""Weekly/monthly reports from actual operations, documents and published plans."""
from datetime import date,datetime,time,timedelta,timezone
from typing import Optional
from sqlalchemy import or_,and_
from sqlalchemy.orm import Session
from app.models import Project,Task,User,Issue,FieldOperation


def period_range(period,ref):
    if period=='week':
        start=ref-timedelta(days=ref.weekday());return start,start+timedelta(days=6)
    start=ref.replace(day=1)
    following=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
    return start,following-timedelta(days=1)


def generate_project_report(db:Session,project:Project,period='week',ref_date:Optional[date]=None,user=None,now=None):
    from zoneinfo import ZoneInfo
    from app.time_utils import project_today
    from app.services.vehicle_progress import progress_totals
    from app.services.field_operations import serialize,text_redactor,effective_records
    from app.services.field_week import plan_cells
    from app.services import project_documents as documents_service
    if user is None:user=db.get(User,project.manager) if project.manager else None
    if user is None or not user.is_active:
        from fastapi import HTTPException
        raise HTTPException(403,'报告需要当前启用的项目查看账号')
    from app.services.scope import ensure_project_visible
    from app.services.system_permissions import has_permission
    if not has_permission(user,'project.read',default=True):
        from fastapi import HTTPException
        raise HTTPException(403,'当前账号没有项目报告查看权限')
    ensure_project_visible(db,project.id,user)
    local_today=project_today(project.timezone);start,end=period_range(period,ref_date or local_today)
    project_zone=ZoneInfo(project.timezone)
    start_dt=datetime.combine(start,time.min,project_zone).astimezone(timezone.utc).replace(tzinfo=None)
    end_dt=datetime.combine(end+timedelta(days=1),time.min,project_zone).astimezone(timezone.utc).replace(tzinfo=None)
    all_records=db.query(FieldOperation).filter_by(project_id=project.id).order_by(FieldOperation.sequence).all()
    records=[row for row in all_records if start<=row.completion_date<=end]
    effective=[row for row in effective_records(all_records) if start<=row.completion_date<=end]
    filter_text=text_redactor(db,project,user)
    completed_items=[serialize(db,row,user,text_filter=filter_text) for row in records]
    people={uid:db.get(User,uid) for uid in {r.actor_id for r in effective} if uid}
    per_person=[{'user_id':uid,'name':person.display_name if person else '历史账号','records':sum(row.actor_id==uid for row in effective),
        'completed':sum(row.actor_id==uid and row.is_done for row in effective),'assisted':sum(row.actor_id==uid and bool(row.assisted_user_id) for row in effective)} for uid,person in people.items()]
    def issue_day(value):return value.replace(tzinfo=timezone.utc).astimezone(project_zone).date().isoformat() if value else ''
    issue_rows=db.query(Issue).filter_by(project_id=project.id).all()
    opened=[i for i in issue_rows if i.created_at and start_dt<=i.created_at<end_dt]
    resolved=[i for i in issue_rows if i.resolved_at and start_dt<=i.resolved_at<end_dt]
    open_issues=[{'id':i.id,'title':i.title,'severity':i.severity,'status':i.status,'created_at':issue_day(i.created_at)} for i in issue_rows if i.status not in ('closed','cancelled')]
    opened_issues=[{'id':i.id,'title':i.title,'severity':i.severity,'created_at':issue_day(i.created_at)} for i in opened]
    resolved_issues=[{'id':i.id,'title':i.title,'severity':i.severity,'resolved_at':issue_day(i.resolved_at),'resolution':i.resolution or ''} for i in resolved]
    next_start=end+timedelta(days=1);next_end=period_range(period,next_start)[1]
    next_cells=plan_cells(db,[project],next_start,max(1,(next_end-next_start).days//7+1))
    from app.services.weekly_plans import serialize_cell
    next_plan=None if next_cells is None else [dict(serialize_cell(db,project,c,user),task=db.get(Task,c.task_id).name if db.get(Task,c.task_id) else '历史工作') for c in next_cells]
    # Document deadlines are the only overdue obligations. Quantity variance stays
    # in plan-versus-actual charts and never becomes a fictitious overdue item.
    from app.models import ProjectDocument,DocumentVersion,Attachment,VehicleLifecycleEvent,VehicleUnit
    from app.services.project_documents import can_read_document,can_read_file,iso
    from app.services.document_deadlines import action_summary
    document_rows=db.query(ProjectDocument).filter_by(project_id=project.id).all()
    documents={row.id:row for row in document_rows if user is None or can_read_document(user,project,row)}
    submissions=[]
    for version,asset in db.query(DocumentVersion,Attachment).join(Attachment,Attachment.id==DocumentVersion.attachment_id).filter(
        DocumentVersion.project_document_id.in_(documents),DocumentVersion.uploaded_at>=start_dt,DocumentVersion.uploaded_at<end_dt).order_by(DocumentVersion.uploaded_at):
        if user is not None and not can_read_file(user,project,asset):continue
        row=documents[version.project_document_id]
        submissions.append({'document_id':row.id,'code':row.code,'name':row.name,'vehicle_label':row.vehicle_label,
            'period_key':row.period_key,'version_id':version.id,'uploaded_at':iso(version.uploaded_at),'uploaded_by':version.uploaded_by,
            'filename':asset.filename,'sha256':asset.sha256})
    vehicle_changes=[]
    for event,unit in db.query(VehicleLifecycleEvent,VehicleUnit).join(VehicleUnit,VehicleUnit.id==VehicleLifecycleEvent.vehicle_unit_id).filter(
        VehicleLifecycleEvent.project_id==project.id,VehicleLifecycleEvent.event_date>=start,VehicleLifecycleEvent.event_date<=end).order_by(VehicleLifecycleEvent.event_date,VehicleLifecycleEvent.id):
        if not event.stage_after and not event.status_after:continue
        vehicle_changes.append({'event_id':event.id,'vehicle_unit_id':unit.id,'asset_code':unit.asset_code,
            'date':event.event_date.isoformat(),'stage_after':event.stage_after,'status_after':event.status_after,
            'title':event.title,'recorded_at':iso(event.created_at),'source':'vehicle_lifecycle_event'})
    document_actions=action_summary(db,project,user,now=now,documents=document_rows)
    document_summary={'submitted':len({row['document_id'] for row in submissions}),'versions':len(submissions),
        'due_in_period':sum(row.due_at is not None and start_dt<=row.due_at<end_dt for row in documents.values()),
        'overdue':document_actions['overdue_count'],'this_week_pending':document_actions['this_week_count']}

    documents_service.audit_access(db,project,user,documents=list(documents.values()))
    from app.config import REPORT_WEEKLY_TIME
    vehicle_actual=[{'event_id':row.id,'vehicle_unit_id':row.target_id,'date':row.completion_date.isoformat(),
        'title':row.target_label,'is_done':row.is_done,'recorded_at':row.recorded_at.isoformat()+'Z','actor_id':row.actor_id,
        'assisted_user_id':row.assisted_user_id,'source':'actual_field_operation'} for row in records if row.kind=='vehicle']
    return {'project':{'id':project.id,'name':project.name,'client':project.client,'location':project.location,'manager':project.manager},
        'period':period,'period_label':f'{start.isoformat()} ~ {end.isoformat()}','generated_at':local_today.isoformat(),
        'weekly_delivery':{'weekday':7,'time':REPORT_WEEKLY_TIME,'timezone':project.timezone},
        'progress':progress_totals(db,project.id),'summary':{'actual_records':len(effective),'completed_work':sum(r.kind=='work' and r.is_done for r in effective),
            'vehicle_completions':sum(r.kind=='vehicle' and r.is_done for r in effective),'assisted_count':sum(bool(r.assisted_user_id) for r in effective),
            'person_count':len(people),'issues_opened':len(opened),'issues_resolved':len(resolved),'open_issues':len(open_issues),
            'next_period_tasks':None if next_plan is None else len(next_plan),'documents_submitted':document_summary['submitted'],
            'document_versions':document_summary['versions'],'vehicle_progress_changes':len(vehicle_changes)+len(vehicle_actual)},
        'completed_items':completed_items,'per_person':per_person,'opened_issues':opened_issues,'resolved_issues':resolved_issues,
        'open_issues':open_issues,'next_plan':next_plan,'next_plan_state':'unavailable' if next_plan is None else 'ready',
        'document_summary':document_summary,'document_submissions':submissions,'vehicle_progress_changes':vehicle_changes+vehicle_actual,
        'risks':document_actions['overdue'][:20]}
