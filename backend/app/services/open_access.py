"""所有账号都能看、都能记录所有项目（config.OPEN_PROJECT_ACCESS，默认开）。

做法不是给权限校验开旁路，而是让每个启用账号自动成为每个项目的成员：
已有的“项目成员”判断（可见、登记、上报、提交资料）原样生效，只是成员名单永远是全员。
- 建项目、改项目、导入/转移项目时，成员同步会补上全部启用账号；
- 新建或重新启用账号时，把他加入全部项目；
- 启动时核对一次，补齐旧数据（每个项目一条操作记录）。
从不因此移除成员：关掉开关后名单保持现状，可在项目里照常调整。
"""
from sqlalchemy.orm import Session

from app import config
from app.models import Project, User


def enabled() -> bool:
    return bool(config.OPEN_PROJECT_ACCESS)


def everyone(db: Session) -> list[str]:
    from app.services.system_permissions import ROLE_NAMES
    return [row.id for row in db.query(User).filter(User.is_active.is_(True)).order_by(User.created_at, User.id).all()
            if row.role in ROLE_NAMES]


def include_everyone(db: Session, project: Project, people: list[str] | None = None) -> list[str]:
    """Add every active account to the project's member list; return who was added."""
    if not enabled():
        return []
    current = list(project.members or [])
    added = [uid for uid in (people if people is not None else everyone(db)) if uid not in current]
    if added:
        project.members = current + added
    return added


def join_all_projects(db: Session, user: User, actor_id: str | None) -> int:
    """A new or re-enabled account joins every project (one audit row for the account)."""
    from app.services.system_permissions import ROLE_NAMES
    if not enabled() or not user.is_active or user.role not in ROLE_NAMES:
        return 0
    from app.routers.projects import _sync_project_members
    from app.services.change_log import log_change
    joined = 0
    for project in db.query(Project).filter(Project.deleted_at.is_(None)).all():
        if user.id in (project.members or []):
            continue
        project.members = [*(project.members or []), user.id]
        _sync_project_members(db, project)
        joined += 1
    if joined:
        log_change(db, None, "user", user.id, "update", actor_id,
                   f"所有账号可见所有项目：「{user.display_name}」加入 {joined} 个项目")
    return joined


