"""Current document attention, project phases and owner-private legacy notes."""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission,route_permission_exempt
from app.db import get_db
from app.deps import get_current_user
from app.services.system_permissions import has_permission
from app.models import User, Project
from app.services.scope import ensure_project_visible
from app.services.progress import project_progress_tree
from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES

router = APIRouter(tags=["洞察"])


def _require_pm_workbench_role(
    user: User,
    message: str = "仅 PM 端角色可使用该功能",
    capability: str = "workspace.view",
):
    """Keep personal ownership/project scope after the configurable action gate."""
    if not has_permission(
        user,
        capability,
        default=user.role in ("admin", "director", "lead", "pm", "technician"),
    ):
        raise HTTPException(status_code=403, detail=message)


@router.get("/projects/{project_id}/overdue")
@route_permission('project.read')
def overdue_tasks(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    """Only real pending document deadlines are overdue; quantities are progress."""
    from app.services.document_deadlines import action_summary
    project=ensure_project_visible(db,project_id,user)
    summary=action_summary(db,project,user)
    return {'count':summary['overdue_count'],'items':summary['overdue'],'timezone':project.timezone,
            'estimated_past_due_count':summary['estimated_past_due_count']}


@router.get("/worker/documents")
@route_permission('project.read')
def worker_document_attention(project_id:Optional[str]=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.scope import visible_projects
    from app.services.document_deadlines import workspace_attention
    projects=[p for p in visible_projects(db,user) if p.status in ACTIVE_PROJECT_STATUSES]
    if project_id:
        project=ensure_project_visible(db,project_id,user)
        projects=[project] if project.status in ACTIVE_PROJECT_STATUSES else []
    return workspace_attention(db,projects,user)


@router.get("/projects/{project_id}/current-phase")
@route_permission('project.read')
def current_phase(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Current phase of a project: farthest template phase with progress,
    plus the chain of all phases with their completion."""
    ensure_project_visible(db, project_id, user)
    from app.services.progress import project_progress_tree

    tree = project_progress_tree(db, project_id)
    chain = []
    current = None
    for ph in tree["phases"]:
        chain.append(
            {"name": ph["name"], "percent": ph["percent"], "color": ph["color"]}
        )
        if ph["percent"] < 100:
            if current is None:
                current = {"name": ph["name"], "percent": ph["percent"]}
    if current is None and tree["phases"]:
        current = {"name": tree["phases"][-1]["name"], "percent": 100}
    return {"current": current, "chain": chain, "overall": tree["percent"]}

