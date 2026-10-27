"""Current visible facts shared by project lists, workbench and statistics.

No schedule simulation, quantity report backlog, effort or synthetic weekly-plan
zero is a current workbench fact. Weekly attention reads canonical published cells.
"""
from collections import Counter
from sqlalchemy import func,or_,case
from app.models import ProjectDocument,User,Issue,VehicleLifecycleEvent,VehicleUnit
from app.services import project_documents as docs
from app.services.document_deadlines import attention_for_projects,action_summary
from app.services.vehicle_progress import progress_totals_batch
from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES

SIGNOFFS=('6.10.1','6.10.2','6.10.3','6.10.4')


def weekly_plan_attention(db,projects,user):
    from app.services.weekly_plans import attention
    return attention(db,projects,user)


def _action(project,item):
    return {**item,'project_id':project.id,'project_name':project.name,'timezone':project.timezone,
            'url':f'/pm/projects/{project.id}/documents?document={item["document_id"]}'}


def project_facts(db,projects,user,*,audit=True):
    projects=list(projects)
    if not projects:return {}
    progress=progress_totals_batch(db,[project.id for project in projects])
    attention=attention_for_projects(db,projects,user)
    rows=db.query(ProjectDocument).filter(ProjectDocument.project_id.in_([p.id for p in projects])).all()
    by_id={row.id:row for row in rows};facts={};audited=set()
    # T23's batch owner map is enough for the same brief formatting; a second
    # bounded query handles the next fixed sign-off without raw row export.
    owner_ids={identity for project in projects for identity in (project.manager,project.technical_manager)}|{row.owner_id for row in rows}
    users={row.id:row for row in db.query(User).filter(User.id.in_(owner_ids))}
    for project in projects:
        summary=attention[project.id]
        active=project.status in ACTIVE_PROJECT_STATUSES
        if not active:summary=action_summary(db,project,user,documents=[],users=users)
        for key in ('this_week','overdue','on_demand','owner_warnings'):
            summary[key]=[_action(project,item) for item in summary[key]]
        signoff=None
        if active:
            candidates=[row for row in rows if row.project_id==project.id and row.code in SIGNOFFS and row.status=='pending'
                        and docs.applicable(project,row) and docs.can_read_document(user,project,row)]
            if candidates:
                row=min(candidates,key=lambda item:(SIGNOFFS.index(item.code),item.vehicle_label or '',item.id))
                from app.services.document_deadlines import owner_details,due_state
                signoff=_action(project,{'id':row.id,'document_id':row.id,'code':row.code,'name':row.name,'status':row.status,
                    'due_at':docs.iso(row.due_at),'due_is_estimated':row.due_is_estimated,'due_basis':row.due_basis,
                    'due_state':due_state(row,project),'period_key':row.period_key,'vehicle_label':row.vehicle_label,
                    **owner_details(project,row,users)})
        vehicle={**progress[project.id],'progress_known':not progress[project.id]['quantity_unknown']}
        facts[project.id]={'vehicle_progress':vehicle,'document_attention':summary,'next_signoff':signoff}
        ids={item['document_id'] for key in ('this_week','overdue','on_demand','owner_warnings') for item in summary[key]}
        if signoff:ids.add(signoff['document_id'])
        if audit:
            visible=[by_id[identity] for identity in ids-audited if identity in by_id]
            docs.audit_access(db,project,user,documents=visible);audited.update(ids)
    if audit:db.commit()
    return facts


def issue_totals_batch(db,project_ids):
    """Same two source families as the project's issue center, without row text."""
    result={pid:{'open':0,'critical':0} for pid in project_ids}
    if not project_ids:return result
    counts=db.query(Issue.project_id,Issue.severity,func.count(Issue.id)).filter(Issue.project_id.in_(project_ids),
        or_(Issue.status.notin_(('closed','cancelled')),Issue.status.is_(None))).group_by(Issue.project_id,Issue.severity).all()
    for pid,severity,number in counts:
        result[pid]['open']+=number
        if severity in ('critical','high'):result[pid]['critical']+=number
    vehicles=db.query(VehicleLifecycleEvent.project_id,func.count(VehicleLifecycleEvent.id),
        func.sum(case((VehicleUnit.current_status.in_(('fault','stopped')),1),else_=0))).join(
            VehicleUnit,VehicleUnit.id==VehicleLifecycleEvent.vehicle_unit_id).filter(
                VehicleLifecycleEvent.project_id.in_(project_ids),VehicleLifecycleEvent.is_closed.is_(False),
                VehicleLifecycleEvent.event_type.in_(('fault','repair','maintenance','inspection','other'))).group_by(VehicleLifecycleEvent.project_id)
    for pid,number,critical in vehicles:
        result[pid]['open']+=number;result[pid]['critical']+=int(critical or 0)
    return result


def issue_totals(db,project_ids):
    rows=issue_totals_batch(db,project_ids).values()
    return {'open':sum(row['open'] for row in rows),'critical':sum(row['critical'] for row in rows)}


def statistics(db,projects,user,*,facts=None):
    projects=list(projects)
    facts=facts if facts is not None else project_facts(db,projects,user,audit=False)
    vehicles=[row['vehicle_progress'] for row in facts.values()]
    target=sum(row['target'] for row in vehicles);completed=sum(row['completed'] for row in vehicles)
    unknown=any(row['quantity_unknown'] for row in vehicles)
    states=Counter(project.status for project in projects)
    return {'projects':len(projects),'active_projects':sum(project.status in ACTIVE_PROJECT_STATUSES for project in projects),
        'completed_projects':sum(project.status in ('completed','archived') for project in projects),
        'status_distribution':[{'status':status,'count':number} for status,number in sorted(states.items())],
        'vehicle_progress':{'target':target,'completed':completed,'quantity_unknown':unknown,
            'unidentified_completed':sum(row['unidentified_completed'] for row in vehicles),
            'percent':None if unknown else (round(completed/target*100,1) if target else 0)},
        'documents':{'this_week_count':sum(row['document_attention']['this_week_count'] for row in facts.values()),
            'overdue_count':sum(row['document_attention']['overdue_count'] for row in facts.values())},
        'issues':issue_totals(db,[project.id for project in projects])}
