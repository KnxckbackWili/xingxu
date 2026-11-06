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

from sqlalchemy.orm import Session
from app.models import Project, User


def visible_projects(db: Session, user: User, *, include_deleted: bool = False) -> list:
    """Every account with project.read sees every project; deleted ones only when asked."""
    from app.services.system_permissions import has_permission

    if not has_permission(user, "project.read", default=True):
        return []
    query = db.query(Project)
    if not include_deleted:
        query = query.filter(Project.deleted_at.is_(None))
    return query.all()


def visible_project_ids(
    db: Session, user: User, *, include_deleted: bool = False
) -> list:
    return [p.id for p in visible_projects(db, user, include_deleted=include_deleted)]


def ensure_project_visible(
    db: Session, project_id: str, user: User, *, include_deleted: bool = False
):
    """项目读校验：项目不存在或已删除时返回 404。"""
    from fastapi import HTTPException
    from app.models import Project
    from app.services.system_permissions import has_permission, permission_override

    if permission_override(user, "project.read") is False:
        raise HTTPException(status_code=403, detail="系统禁止：查看项目（project.read）")
    p = db.get(Project, project_id)
    if p is None or (p.deleted_at is not None and not include_deleted) or not has_permission(user, "project.read", default=True):
        raise HTTPException(status_code=404, detail="项目不存在")
    return p


def can_manage_project(user: User, project: Project) -> bool:
    """Who can manage a project (PM actions)."""
    if user.role in ("admin", "director"):
        return True
    return user.role in ("pm", "lead") and project.manager == user.id


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
