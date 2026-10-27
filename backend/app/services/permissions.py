"""项目级能力权限（v1.2.1）。

权限模型 = 系统角色（users.role）+ 项目关系（project.manager / members）→ 操作能力。
- 系统动作授权由 system_permissions 统一计算；项目权限仍受可见范围与生命周期约束。
- 项目能力由 project_capabilities() 计算，写端点用 require_project_capability()
  或 authorize_project() 校验。

基线（评审 v1.2.1）：
  admin                    → 全部项目能力
  director                 → 全局查看、问题治理、归档、导出与审批
  pm（该项目负责人）         → 项目管理；有删除能力可直接备份后移入回收站
  lead/technician（技术负责人）→ 任务、日程、问题、导出
  technician/worker/intern  → 只读（填报/交付/上报走独立成员端点）

权限语义：
- 项目不可见 → 404（ensure_project_visible，不泄露存在性）
- 项目可见但无该能力 → 403
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User, Project
from app.services.scope import ensure_project_visible
from app.services.scope import active_co_manager

# ===== 项目能力常量 =====
C_READ = "project.read"  # 查看（可见性，由 ensure_project_visible 覆盖）
C_UPDATE = "project.update"  # 核心资料/车型/状态流转/删除附件
C_MEMBERS = "project.manage_members"  # 成员与定岗
C_PLAN = "project.manage_plan"  # 任务生成/调整/检查项适用性
C_SCHEDULE = "project.manage_schedule"  # 日程生成/拖拽/确认
C_ISSUES = "project.manage_issues"  # 问题更新/删除/指派
C_EXPORT = "project.export"  # 导出（Excel/JSON）
C_ARCHIVE = "project.archive"  # 归档清单
C_INVENTORY = "project.manage_inventory"  # 现场物品台账与流水
C_DELETE = "project.delete"  # 删除项目

ALL_PROJECT_CAPS = {
    C_UPDATE,
    C_MEMBERS,
    C_PLAN,
    C_SCHEDULE,
    C_ISSUES,
    C_EXPORT,
    C_ARCHIVE,
    C_INVENTORY,
    C_DELETE,
}


# Explicit member grants never include deletion, global roles, or delegation rights.
GRANTABLE_PROJECT_CAPS = ALL_PROJECT_CAPS - {C_DELETE}


def grantable_project_capabilities(user: User, project: Project) -> set:
    """Only the administrator or project owner may delegate their own privileges."""
    if user.role == "admin" or (
        project.manager == user.id and user.role in ("pm", "lead")
    ):
        return project_capabilities(user, project) & GRANTABLE_PROJECT_CAPS
    return set()


def project_capabilities(user: User, project: Project) -> set:
    """Combine existing relation permissions with bounded, project-local grants."""
    caps = inherited_project_capabilities(user, project)
    if user.id in (project.members or []):
        for grant in project.member_permissions or []:
            if grant.get("user_id") == user.id:
                caps.update(
                    set(grant.get("capabilities") or []) & GRANTABLE_PROJECT_CAPS
                )
    from app.services.system_permissions import permission_override

    for capability in ALL_PROJECT_CAPS:
        choice = permission_override(user, capability)
        if choice is False:
            caps.discard(capability)
        elif choice is True:
            caps.add(capability)
    if user.role == "readonly":
        caps.intersection_update({C_EXPORT})
    return caps


def inherited_project_capabilities(user: User, project: Project) -> set:
    """当前用户对某项目的能力集合（不含 C_READ，可见性单独校验）。"""
    if user.role == "readonly":
        return {C_EXPORT}
    if user.role == "admin":
        return set(ALL_PROJECT_CAPS)
    if user.role == "director":
        return {C_ISSUES, C_EXPORT, C_ARCHIVE}
    if project.manager == user.id and user.role in ("pm", "lead"):
        return {
            C_UPDATE,
            C_MEMBERS,
            C_PLAN,
            C_SCHEDULE,
            C_ISSUES,
            C_EXPORT,
            C_ARCHIVE,
            C_INVENTORY,
            C_DELETE,
        }
    if active_co_manager(project, user.id) and user.role in (
        "pm",
        "technician",
        "worker",
        "lead",
        "intern",
    ):
        return {
            C_UPDATE,
            C_MEMBERS,
            C_PLAN,
            C_SCHEDULE,
            C_ISSUES,
            C_EXPORT,
            C_ARCHIVE,
            C_INVENTORY,
        }
    if project.technical_manager == user.id and user.role in (
        "lead",
        "technician",
        "pm",
        "worker",
    ):
        return {C_PLAN, C_SCHEDULE, C_ISSUES, C_EXPORT, C_INVENTORY}
    return set()


def authorize_project(user: User, project: Project, capability: str) -> None:
    """项目可见性 + 能力校验（写操作 handler 内用）。"""
    if capability not in project_capabilities(user, project):
        from app.services.permission_explanations import action_denial
        raise HTTPException(status_code=403, detail=action_denial(user, capability))


def require_project_capability(capability: str):
    """FastAPI dependency 工厂：URL 带 project_id 的写端点直接声明。"""

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
