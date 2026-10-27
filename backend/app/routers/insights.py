"""Current document attention, project phases and owner-private legacy notes."""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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


class PersonalEventCreate(BaseModel):
    """HYPE-89：个人临时日程创建/更新字段（标题 + 日期 + 备注 + 归属项目；不挂任务）。

    project_id 为记录归属（日历显示挂在哪个项目），必填；项目日程页与团队日程
    仍是任务排班口径，不含临时事项。"""

    model_config = {"extra": "forbid"}

    project_id: str = Field(..., min_length=1)
    work_date: date
    title: str = Field(..., min_length=1, max_length=100)
    notes: str = Field("", max_length=500)


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
    db: Session, events: list[PersonalEvent]
) -> dict[str, Optional[str]]:
    """批量解析事件归属项目名；历史 NULL 行（理论上无）返回 None，前端显示「（未绑定）」。"""
    pids = {e.project_id for e in events if e.project_id}
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
    q = (
        db.query(PersonalEvent)
        .join(Project, Project.id == PersonalEvent.project_id)
        .filter(PersonalEvent.user_id == user.id)
    )
    if from_date:
        q = q.filter(PersonalEvent.work_date >= from_date)
    if to_date:
        q = q.filter(PersonalEvent.work_date <= to_date)
    rows = q.order_by(PersonalEvent.work_date, PersonalEvent.id).all()
    names = _personal_event_names(db, rows)
    return [_personal_event_dict(e, names.get(e.project_id)) for e in rows]


def _visible_project_or_404(db: Session, project_id: str, user: User) -> Project:
    """HYPE-89：临时日程归属项目校验——存在且对当前用户可见（与 self add 同型，404 不泄露）。"""
    from app.services.scope import visible_project_ids

    proj = db.get(Project, project_id)
    if proj is None or proj.id not in set(visible_project_ids(db, user)):
        raise HTTPException(status_code=404, detail="项目不存在")
    return proj


@router.post("/dashboard/personal-events")
@route_permission('personal.schedule.manage')
def create_personal_event(
    data: PersonalEventCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HYPE-88：新增个人临时日程（不挂项目任务，执行人固定当前登录者）。"""
    _require_pm_workbench_role(user, "没有个人日程管理权限", "personal.schedule.manage")
    proj = _visible_project_or_404(db, data.project_id, user)
    e = PersonalEvent(
        user_id=user.id,
        project_id=proj.id,
        work_date=data.work_date,
        title=data.title,
        notes=data.notes,
    )
    db.add(e)
    db.commit()
    return {"message": "临时日程已添加", "event": _personal_event_dict(e, proj.name)}


def _get_own_personal_event_or_404(
    db: Session, event_id: str, user: User
) -> PersonalEvent:
    """他人条目与不存在条目统一 404，不泄露越权资源存在性。"""
    e = db.get(PersonalEvent, event_id)
    if e is None or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="个人事项不存在")
    return e


@router.put("/dashboard/personal-events/{event_id}")
@route_permission('personal.schedule.manage')
def update_personal_event(
    event_id: str,
    data: PersonalEventCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HYPE-88：修改本人临时日程（标题 / 日期 / 备注；单人读写，无乐观锁）。"""
    _require_pm_workbench_role(user, "没有个人日程管理权限", "personal.schedule.manage")
    e = _get_own_personal_event_or_404(db, event_id, user)
    proj = _visible_project_or_404(db, data.project_id, user)  # HYPE-89：允许改绑项目
    e.work_date = data.work_date
    e.project_id = proj.id
    e.title = data.title
    e.notes = data.notes
    db.commit()
    return {"message": "临时日程已更新", "event": _personal_event_dict(e, proj.name)}


@router.delete("/dashboard/personal-events/{event_id}")
@route_permission('personal.schedule.manage')
def delete_personal_event(
    event_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HYPE-88：删除本人临时日程（他人条目一律 404）。"""
    _require_pm_workbench_role(user, "没有个人日程管理权限", "personal.schedule.manage")
    e = _get_own_personal_event_or_404(db, event_id, user)
    db.delete(e)
    db.commit()
    return {"message": "临时日程已删除"}


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
