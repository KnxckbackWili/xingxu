"""Current document attention, project phases and owner-private legacy notes."""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission,route_permission_exempt
from app.db import get_db
from app.deps import get_current_user
from app.services.system_permissions import has_permission
from app.models import User, Project, PersonalEvent
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


def _personal_event_names(
    db: Session, events: list[PersonalEvent], user: User
) -> dict[str, Optional[str]]:
    """批量解析事件归属项目名，只返回当前用户可见项目的名称。

    旧个人事项归原所有者只读，但所有者已不可见的项目，其当前名称不能借此泄露；
    历史 NULL 行或不可见项目返回 None，前端显示「（未绑定）」。
    """
    from app.services.scope import visible_project_ids
    pids = {e.project_id for e in events if e.project_id} & set(visible_project_ids(db, user))
    if not pids:
        return {}
    return {p.id: p.name for p in db.query(Project).filter(Project.id.in_(pids)).all()}


def _personal_event_dict(e: PersonalEvent, project_name: Optional[str] = None) -> dict:
    return {
        "id": e.id,
        "project_id": e.project_id,
        "project_name": project_name,
        "work_date": e.work_date.isoformat(),
        "title": e.title,
        "notes": e.notes,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("/dashboard/personal-events")
@route_permission('personal.schedule.read')
def list_personal_events(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HYPE-88：当前登录者的个人临时日程（单人读写，只返回本人条目）。"""
    _require_pm_workbench_role(user, "没有个人日程查看权限", "personal.schedule.read")
    # Owner history includes rows whose project was never recorded (legacy NULL).
    q = db.query(PersonalEvent).filter(PersonalEvent.user_id == user.id)
    if from_date:
        q = q.filter(PersonalEvent.work_date >= from_date)
    if to_date:
        q = q.filter(PersonalEvent.work_date <= to_date)
    rows = q.order_by(PersonalEvent.work_date, PersonalEvent.id).all()
    names = _personal_event_names(db, rows, user)
    return [_personal_event_dict(e, names.get(e.project_id)) for e in rows]


@router.post("/dashboard/personal-events")
@router.put("/dashboard/personal-events/{event_id}")
@router.delete("/dashboard/personal-events/{event_id}")
@route_permission_exempt('旧个人临时日程已随按日排程退役；认证后仅返回410，原条目归所有者只读保留')
def retired_personal_event_mutations(user: User = Depends(get_current_user)):
    raise HTTPException(410, "个人临时日程已退役，原条目只读保留；新安排请使用项目周计划")


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


@router.post("/dashboard/people-plan/self")
@router.get("/dashboard/team-schedule")
@router.get("/worker/overdue")
@router.get("/dashboard/people-plan")
@router.put("/dashboard/people-plan/{entry_id}/self")
@router.get("/dashboard/workload")
@router.get("/north-star")
@router.get("/dashboard/staffing")
@route_permission_exempt('旧按日数量、日程或耗时统计已由周计划与当前事实替代；认证后只返回410')
def retired_daily_projection(user:User=Depends(get_current_user)):
    raise HTTPException(410,'该按日安排或数量统计已退役，请使用人员周计划、本周或当前统计')
