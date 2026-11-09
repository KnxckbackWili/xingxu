"""Project actions. Every employee does project work; administrators do everything.

- Project visibility: ensure_project_visible (404 for missing or deleted projects).
- A project write checks the action with authorize_project or require_project_capability,
  then the lifecycle (archived/suspended projects are read-only).
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User, Project
from app.services.scope import ensure_project_visible

C_READ = "project.read"
C_UPDATE = "project.update"  # 项目资料、车型、状态
C_PLAN = "project.manage_plan"  # 工作项、检查与资料要求
C_SCHEDULE = "project.manage_schedule"  # 周计划
C_ISSUES = "project.manage_issues"  # 问题
C_EXPORT = "project.export"
C_ARCHIVE = "project.archive"
C_INVENTORY = "project.manage_inventory"
C_DELETE = "project.delete"

ALL_PROJECT_CAPS = {C_UPDATE, C_PLAN, C_SCHEDULE, C_ISSUES, C_EXPORT, C_ARCHIVE, C_INVENTORY, C_DELETE}


def project_capabilities(user: User, project: Project) -> set:
    from app.services.system_permissions import has_permission
    return {capability for capability in ALL_PROJECT_CAPS if has_permission(user, capability)}


def authorize_project(user: User, project: Project, capability: str) -> None:
    if capability not in project_capabilities(user, project):
        from app.services.system_permissions import PERMISSIONS
        name = PERMISSIONS.get(capability, {}).get("name", capability)
        raise HTTPException(status_code=403, detail=f"没有权限：{name}")


def require_project_capability(capability: str):
    """FastAPI dependency factory for routes with project_id in the URL."""

    def checker(
        project_id: str,
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Project:
        p = ensure_project_visible(db, project_id, user)
        authorize_project(user, p, capability)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            from app.services.project_lifecycle import ensure_project_writable

            ensure_project_writable(p)
        return p

    return checker
