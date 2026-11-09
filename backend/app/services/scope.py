"""Which projects an account can open: every active account sees every project."""

from sqlalchemy.orm import Session
from app.models import Project, User


def visible_projects(db: Session, user: User, *, include_deleted: bool = False) -> list:
    """Every account with project.read sees every project; deleted ones only when asked."""
    from app.services.system_permissions import has_permission

    if not has_permission(user, "project.read"):
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
    from app.services.system_permissions import has_permission

    p = db.get(Project, project_id)
    if p is None or (p.deleted_at is not None and not include_deleted) or not has_permission(user, "project.read"):
        raise HTTPException(status_code=404, detail="项目不存在")
    return p
