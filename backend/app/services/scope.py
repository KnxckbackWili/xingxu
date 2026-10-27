"""Project visibility scope per role & org — the single source of truth
for what each user can see.

Roles (7 levels, extensible):
    admin      系统管理员     — 全系统
    director   总监           — 全部项目总览 + 治理审批
    lead       技术经理       — 被指定项目的技术管理
    pm         项目经理       — 自己管理的项目
    technician 技术工程师     — 被指定或参与的项目
    worker     实施工程师     — 参与项目总览 + 今日任务 + 自己规划
    intern     实习工程师     — 参与项目（受限填报）
"""

from datetime import date
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models import Project, User, ProjectMember


def active_co_manager(
    project: Project, user_id: str, on_date: Optional[date] = None
) -> bool:
    """Whether a project-scoped co-manager grant is active today."""
    today = on_date or date.today()
    for grant in project.co_managers or []:
        if grant.get("user_id") != user_id:
            continue
        expires_at = grant.get("expires_at")
        if not expires_at:
            return True
        try:
            return date.fromisoformat(expires_at) >= today
        except (TypeError, ValueError):
            return False
    return False


def visible_projects(db: Session, user: User, *, include_deleted: bool = False) -> list:
    """Projects visible to the user under their role scope.

    已从“全表拉出再 Python 过滤”改为 project_members 关系表 JOIN，
    避免 500 个项目时每个接口都全量扫描 JSON 成员字段。
    """
    query = db.query(Project)
    if not include_deleted:
        query = query.filter(Project.deleted_at.is_(None))
    from app.services.system_permissions import has_permission

    if not has_permission(user, "project.read", default=True):
        return []
    if has_permission(
        user, "projects.view_all", default=user.role in ("admin", "director")
    ):
        # C8-4：软删除项目对所有人不可见（包括 admin/director），仅恢复时可查
        return query.all()

    member_ids = [
        row[0]
        for row in db.query(ProjectMember.project_id)
        .filter(ProjectMember.user_id == user.id)
        .all()
    ]
    if member_ids:
        return query.filter(Project.id.in_(member_ids)).all()

    # 旧数据兼容：project_members 尚未同步时回退 JSON 判断
    projects = query.all()
    if user.role in ("pm", "lead", "admin", "director"):
        return [
            p
            for p in projects
            if p.manager == user.id
            or p.technical_manager == user.id
            or user.id in (p.members or [])
            or active_co_manager(p, user.id)
        ]
    if user.role in ("worker", "technician", "intern", "readonly"):
        return [
            p
            for p in projects
            if user.id in (p.members or [])
            or p.technical_manager == user.id
            or active_co_manager(p, user.id)
        ]
    return []


def visible_project_ids(
    db: Session, user: User, *, include_deleted: bool = False
) -> list:
    return [p.id for p in visible_projects(db, user, include_deleted=include_deleted)]


def ensure_project_visible(
    db: Session, project_id: str, user: User, *, include_deleted: bool = False
):
    """项目读校验：不在用户可见范围内返回 404（不泄露项目存在性）。

    全系统读端点统一走这里（worker 只能读自己参与的项目，PM 读自己管的项目）。
    """
    from fastapi import HTTPException
    from app.models import Project
    from app.services.system_permissions import permission_override

    if permission_override(user, "project.read") is False:
        raise HTTPException(status_code=403, detail="系统禁止：查看项目（project.read）")
    p = db.get(Project, project_id)
    if p is None or p.id not in visible_project_ids(
        db, user, include_deleted=include_deleted
    ):
        raise HTTPException(status_code=404, detail="项目不存在，或你不是项目成员且未获查看权限")
    return p


def can_manage_project(user: User, project: Project) -> bool:
    """Who can manage a project (PM actions)."""
    if user.role in ("admin", "director"):
        return True
    if user.role in ("pm", "lead"):
        return project.manager == user.id or active_co_manager(project, user.id)
    if user.role in ("worker", "technician", "intern", "readonly"):
        return active_co_manager(project, user.id)
    return False


def role_label(role: str) -> str:
    return {
        "admin": "系统管理员",
        "director": "总监",
        "lead": "技术经理",
        "pm": "项目经理",
        "technician": "技术工程师",
        "worker": "实施工程师",
        "intern": "实习工程师",
    }.get(role, role)
