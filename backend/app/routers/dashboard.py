"""Executive dashboard: cross-project portfolio overview for leadership."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from app.services.system_permissions import route_permission,route_permission_exempt
from app.db import get_db
from app.deps import get_current_user
from app.services.system_permissions import has_permission
from app.models import User, Project, Issue, Task
from app.services.progress import task_progress_maps, execution_tasks_for_projects
from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES

def _private_response(response:Response):
    response.headers["Cache-Control"]="private, no-store"


router = APIRouter(tags=["总览"],dependencies=[Depends(_private_response)])


def _project_progress_totals(db: Session, tasks: list[Task], project_ids=None) -> dict:
    """Every live portfolio view uses the same equal-weight work contract."""
    from app.services.vehicle_progress import progress_totals_batch
    completed,targets,percentages=task_progress_maps(db,tasks)
    pids=set(project_ids or []) | {t.project_id for t in tasks}
    matrices=progress_totals_batch(db,pids)
    totals={pid:{'target':m['target'],'completed':m['completed'],'quantities_by_unit':{},'vehicle_progress':m} for pid,m in matrices.items()}
    for task in tasks:
        row=totals[task.project_id]
        unit=(task.unit or '项').strip() or '项'
        group=row['quantities_by_unit'].setdefault(unit,{'unit':unit,'completed':0,'target':0})
        group['completed']+=completed[task.id];group['target']+=targets[task.id]
        if task.quantity_type!='per_vehicle' and targets[task.id]>0:
            row['target']+=1
            row['completed']+=int(percentages[task.id]>=100)
    for row in totals.values():
        row['quantities_by_unit']=[{**g,'completed':round(g['completed'],3),'target':round(g['target'],3)} for g in row['quantities_by_unit'].values()]
        row['percent']=round(row['completed']/row['target']*100,1) if row['target'] else 0
    return totals


@router.get("/dashboard/issues")
@route_permission('project.read')
def scope_issues(
    include_closed: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Open issues across the user's visible projects (per role scope)."""
    from app.services.scope import visible_projects, active_co_manager
    from app.models import VehicleLifecycleEvent, VehicleUnit

    projects = visible_projects(db, user)
    pids = [p.id for p in projects]
    if not pids:
        return {
            "count": 0,
            "count_7d_ago": 0,
            "trend": [0, 0, 0, 0, 0, 0, 0],
            "items": [],
        }
    rows = (
        db.query(Issue, Project.name)
        .join(Project, Project.id == Issue.project_id)
        .filter(Issue.project_id.in_(pids))
        .filter(True if include_closed else Issue.status.in_(["open", "processing"]))
        .order_by(Issue.created_at.desc())
        .all()
    )
    project_by_id = {project.id: project for project in projects}
    from app.services.document_triggers import issue_events,issue_sla_fields
    trigger_sources=issue_events(db,[row[0] for row in rows])
    items = [
        {
            "id": i.id,
            "source": "project",
            **issue_sla_fields(db,i,trigger_sources),
            "version": i.version or 0,
            "title": i.title,
            "severity": i.severity,
            "status": i.status,
            "project_id": i.project_id,
            "project_name": pname,
            "created_at": i.created_at.isoformat() if i.created_at else "",
            "reporter_id": i.reporter_id,
            "assignee_id": i.assignee_id,
            "project_status": project_by_id[i.project_id].status,
            "assignee_name": (
                db.get(User, i.assignee_id).display_name
                if i.assignee_id and db.get(User, i.assignee_id)
                else ""
            ),
            "description": i.description or "",
            "resolution": i.resolution or "",
            "issue_type": i.issue_type,
            "extra": i.extra or {},
        }
        for i, pname in rows
        if user.role not in ("worker", "intern")
        or i.reporter_id == user.id
        or i.assignee_id == user.id
        or active_co_manager(project_by_id[i.project_id], user.id)
    ]
    project_names = {project.id: project.name for project in projects}
    vehicle_rows = (
        db.query(VehicleLifecycleEvent, VehicleUnit)
        .join(VehicleUnit, VehicleUnit.id == VehicleLifecycleEvent.vehicle_unit_id)
        .filter(
            VehicleLifecycleEvent.project_id.in_(pids),
            VehicleLifecycleEvent.event_type.in_(
                ("fault", "repair", "maintenance", "inspection", "other")
            ),
            VehicleLifecycleEvent.is_closed.is_(False),
        )
        .order_by(VehicleLifecycleEvent.event_date.desc())
        .all()
    )
    for event, unit in vehicle_rows:
        project = project_by_id.get(event.project_id)
        if event.operator_id != user.id and (
            not (project and active_co_manager(project, user.id))
        ):
            continue
        items.append(
            {
                "id": event.id,
                "source": "vehicle",
                "title": event.title,
                "severity": (
                    "high" if unit.current_status in ("fault", "stopped") else "medium"
                ),
                "status": "open",
                "project_id": event.project_id,
                "project_name": project_names.get(event.project_id, ""),
                "created_at": event.event_date.isoformat(),
                "reporter_id": event.operator_id,
                "assignee_name": event.handler or "",
                "description": event.description or "",
                "resolution": event.action_taken or "",
                "asset_code": unit.asset_code,
            }
        )
    from datetime import date, timedelta

    today = date.today()
    as_of = today - timedelta(days=7)
    created_dates = []
    for item in items:
        try:
            created_dates.append(date.fromisoformat(item["created_at"].split("T")[0]))
        except (TypeError, ValueError):
            pass
    trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        trend.append(sum((1 for d in created_dates if d <= day)))
    return {
        "count": len(items),
        "count_7d_ago": sum((1 for d in created_dates if d <= as_of)),
        "trend": trend,
        "items": items,
    }


@router.get("/dashboard/overview")
@route_permission('workspace.view')
def portfolio_overview(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    """Current facts only; never cache private titles across a scope change."""
    if not has_permission(user,'workspace.view'):raise HTTPException(403,'没有查看工作台权限')
    from app.services.scope import visible_projects
    from app.services import workbench
    from app.time_utils import utcnow
    projects=visible_projects(db,user)
    facts=workbench.project_facts(db,projects,user)
    canonical=_project_progress_totals(db,execution_tasks_for_projects(db,[p.id for p in projects]),[p.id for p in projects])
    counts=workbench.issue_totals_batch(db,[p.id for p in projects])
    items=[]
    for project in projects:
        totals=canonical[project.id];project_facts=facts[project.id]
        issues=counts.get(project.id,{'open':0,'critical':0})
        items.append({'id':project.id,'name':project.name,'client':project.client,'status':project.status,
            'start_date':project.start_date,'end_date':project.end_date,'created_at':project.created_at,
            'percent':totals['percent'] if project_facts['vehicle_progress']['progress_known'] else None,
            'progress_known':project_facts['vehicle_progress']['progress_known'],
            'target':totals['target'],'completed':totals['completed'],'open_issues':issues['open'],'critical_issues':issues['critical'],
            'overdue':bool(project_facts['document_attention']['overdue_count']),**project_facts})
    aggregate=workbench.statistics(db,projects,user,facts=facts)
    this_week=[item for facts in facts.values() for item in facts['document_attention']['this_week']]
    this_week.sort(key=lambda item:(item['due_at'] or '9999',item['project_id'],item['document_id']))
    return {'generated_at':utcnow().isoformat()+'Z','projects':items,'status_distribution':aggregate['status_distribution'],
        'stats':{'total_projects':aggregate['projects'],'active_projects':aggregate['active_projects'],
            'completed_projects':aggregate['completed_projects'],'open_issues':aggregate['issues']['open'],
            'critical_issues':aggregate['issues']['critical'],'overdue_projects':sum(bool(row['document_attention']['overdue_count']) for row in facts.values())},
        'this_week_documents':this_week,'weekly_plan':workbench.weekly_plan_attention(db,projects,user)}


@router.get('/dashboard/statistics')
@route_permission('insights.view')
def workspace_statistics(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if not has_permission(user,'insights.view'):raise HTTPException(403,'没有查看统计权限')
    from app.services.scope import visible_projects
    from app.services.workbench import statistics
    return statistics(db,visible_projects(db,user),user)


@router.get('/dashboard/documents')
@route_permission('project.read')
def document_attention(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.scope import visible_projects
    from app.services.document_deadlines import workspace_attention
    projects=[p for p in visible_projects(db,user) if p.status in ACTIVE_PROJECT_STATUSES]
    return workspace_attention(db,projects,user)


@router.get('/dashboard/overdue')
@route_permission('project.read')
def overdue_projects(limit:int=Query(500,ge=1,le=1000),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    summary=document_attention(user,db)
    projects=[{'project_id':row['project_id'],'project_name':row['project_name'],'count':row['overdue_count'],
               'items':[{**item,'timezone':row['timezone']} for item in row['overdue']]} for row in summary['projects'] if row['overdue_count']]
    projects.sort(key=lambda row:(-row['count'],row['project_id']))
    # No historical quantity backlog is relabelled as a document trend.
    return {'count':summary['overdue_count'],'projects':projects[:limit],
            'this_week_count':summary['this_week_count'],'this_week':summary['this_week'],
            'estimated_past_due_count':summary['estimated_past_due_count']}


@router.get("/dashboard/assignment-pool")
@router.get("/dashboard/trend")
@router.get("/dashboard/metrics")
@router.get("/dashboard/people-workload")
@router.get("/dashboard/people-overview")
@router.get("/dashboard/people-summary")
@router.get("/dashboard/stats")
@router.get("/dashboard/decision-view")
@route_permission_exempt('旧按日数量、日程或耗时统计已由周计划与当前事实替代；认证后只返回410')
def retired_daily_projection(user:User=Depends(get_current_user)):
    raise HTTPException(410,'该按日安排或数量统计已退役，请使用人员周计划、本周或当前统计')
