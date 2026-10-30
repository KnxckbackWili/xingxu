"""Progress routes."""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.scope import ensure_project_visible
from app.services.progress import project_progress_tree, plan_vs_actual_timeline
from app.services.system_permissions import has_permission

router = APIRouter(tags=["进度"])
# Overview "recent activity" shows people's changes; access audits, automatic deadline recalculation and the raw
# upload record (always followed by the document submission it served) and documents the schedule creates by itself stay
# on the full audit page.
ACCESS_AUDIT_ACTIONS = ('confidential_view', 'confidential_dl', 'confidential_export', 'deadline')


@router.get("/projects/{project_id}/progress")
@route_permission('project.read')
def progress(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    return project_progress_tree(db, project_id)


@router.get("/projects/{project_id}/progress/timeline")
@route_permission('project.read')
def timeline(
    project_id: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_project_visible(db, project_id, user)
    return plan_vs_actual_timeline(db, project_id, from_date, to_date)


@router.get("/projects/{project_id}/overview")
@route_permission('project.read')
def project_overview(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """聚合端点：一次返回项目总览页所需数据，避免前端 8 个请求打满浏览器。
    返回结构：progress / timeline / overdue / issues / tree / logs / preparations / weekly_plans。
    """
    from app.models import Issue, Task, ChangeLog, User as UserModel
    from app.routers.preparations import _summary
    from app.routers.tasks import get_project_tree

    project = ensure_project_visible(db, project_id, user)
    progress_tree = project_progress_tree(db, project_id)
    timeline_data = plan_vs_actual_timeline(db, project_id, None, None)
    issues = db.query(Issue).filter(Issue.project_id == project_id).order_by(Issue.created_at.desc()).all()
    from app.services.weekly_plans import project_summary
    weekly_summary=project_summary(db,project,user)
    tree = get_project_tree(project_id, user, db)
    prep_summary = _summary(db, project)
    from app.services.project_documents import progress_summary
    from app.services.document_deadlines import action_summary

    from app.models import ProjectDocument
    document_rows=db.query(ProjectDocument).filter_by(project_id=project_id).all()
    document_actions=action_summary(db,project,user,documents=document_rows)
    overdue_data={"count":document_actions["overdue_count"],"items":document_actions["overdue"]}
    overdue = [{**item, "id": item["document_id"]} for item in overdue_data["items"]]
    logs = db.query(ChangeLog).filter(ChangeLog.project_id == project_id, ChangeLog.action.notin_(ACCESS_AUDIT_ACTIONS), ~((ChangeLog.entity_type == 'attachment') & (ChangeLog.action == 'create')), ~((ChangeLog.entity_type == 'project_document') & (ChangeLog.action == 'generate'))).order_by(ChangeLog.created_at.desc()).limit(20).all() if has_permission(user, "system.audit.read") else []
    task_names = {t.id: t.name for t in db.query(Task).filter(Task.project_id == project_id).all()}

    reporter_ids = {i.reporter_id for i in issues}
    assignee_ids = {i.assignee_id for i in issues if i.assignee_id}
    user_ids = reporter_ids | assignee_ids | {l.operator_id for l in logs if l.operator_id}
    user_names = {u.id: u.display_name for u in db.query(UserModel).filter(UserModel.id.in_(user_ids)).all()}
    for item in overdue:
        item['assignee_name'] = user_names.get(item.get('assignee_id'), '')

    issue_dicts = []
    for i in issues:
        issue_dicts.append({
            "id": i.id,
            "title": i.title,
            "description": i.description,
            "issue_type": i.issue_type,
            "extra": i.extra or {},
            "severity": i.severity,
            "status": i.status,
            "reporter_name": user_names.get(i.reporter_id, ''),
            "assignee_id": i.assignee_id,
            "assignee_name": user_names.get(i.assignee_id, ''),
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "resolution": i.resolution,
        })

    log_dicts = []
    for l in logs:
        log_dicts.append({
            "id": l.id,
            "entity_type": l.entity_type,
            "action": l.action,
            "detail": l.detail,
            "operator_name": user_names.get(l.operator_id, ''),
            "created_at": l.created_at.isoformat() if l.created_at else None,
        })

    from app.services.acceptance import acceptance_summary
    from app.services.project_events import event_state
    return {
        "project_events": event_state(db, project),
        "acceptance_summary": acceptance_summary(db, project_id),
        "progress": progress_tree,
        "timeline": timeline_data,
        "overdue": {**overdue_data, "items": overdue},
        "issues": issue_dicts,
        "tree": tree,
        "logs": log_dicts,
        "document_progress": progress_summary(db,project,user,documents=document_rows),
        "document_actions":document_actions,
        "preparations": {"summary": prep_summary},
        "weekly_plans": weekly_summary,
        "project": {
            "id": project.id,
            "name": project.name,
            "status": project.status,
        },
    }
