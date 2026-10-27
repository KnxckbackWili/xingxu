from typing import Optional, Literal

"""User management routes (admin only)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission, route_permission_contextual, route_permission_exempt
from app.db import get_db
from app.deps import require_admin, get_current_user
from app.models import User
from app.services.change_log import log_change
from app.services.system_permissions import has_permission

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/users", tags=["用户管理"])


_ROLE_RE = "^(admin|director|lead|pm|technician|worker|intern|readonly)$"


class UserCreate(BaseModel):
    username: Optional[str] = Field(
        default=None, max_length=50
    )  # 留空 = 用姓名作为登录用户名
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(default="worker", pattern=_ROLE_RE)
    permission_preset: Literal["pm", "worker", "readonly"] | None = None
    phone: str = ""
    email: str = ""


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern=_ROLE_RE)
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "phone": u.phone or "",
        "email": u.email or "",
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _audit_fields(user: User) -> dict:
    """Account audit snapshots never include credentials or contact details."""
    return {
        key: getattr(user, key)
        for key in ("username", "display_name", "role", "is_active")
    }


@router.get("", response_model=list)
@route_permission_contextual('system.users.read', 'system.users.manage', reason='处理器按查看或维护权限返回人员目录')
def list_users(admin: User = Depends(get_current_user), db: Session = Depends(get_db)):
    full = has_permission(
        admin, "system.users.read", default=admin.role == "admin"
    ) or has_permission(admin, "system.users.manage", default=admin.role == "admin")
    if not full:
        raise HTTPException(403, "没有人员列表查看权限")
    users = db.query(User).order_by(User.created_at).all()
    items = [_user_dict(u) for u in users]
    if not full:
        for item in items:
            item.update(username="", phone="", email="")
    return items


@router.post("", response_model=dict)
@route_permission('system.users.manage')
def create_user(
    data: UserCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    role = data.permission_preset or data.role
    if admin.role != "admin" and role not in {"worker", "readonly"}:
        raise HTTPException(
            403, "只有系统管理员可以指定账号角色；受委托成员只能创建实施工程师或只读账号"
        )
    username = (data.username or data.display_name).strip()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(
            status_code=400, detail="用户名已存在（与姓名或其他账号重复）"
        )
    u = User(
        username=username,
        password_hash=pwd_context.hash(data.password),
        display_name=data.display_name,
        role=role,
        phone=data.phone,
        email=data.email,
    )
    db.add(u)
    db.flush()
    log_change(
        db,
        None,
        "user",
        u.id,
        "create",
        admin.id,
        f"创建用户「{u.display_name}」",
        None,
        _audit_fields(u),
    )
    db.commit()
    db.refresh(u)
    return _user_dict(u)


def _lock_account_changes(
    db: Session, admin: User, capability: str = "system.users.manage"
) -> None:
    """Serialize administrator retirement decisions on one stable account row.

    Locking only the account being edited allows two administrators to each
    observe the other as the remaining admin, then retire both concurrently.
    The built-in account cannot be deleted and is a stable serialization point.
    """
    from app.services.record_lock import lock_record

    anchor = db.query(User).filter(User.username == "admin").first()
    if anchor is None:
        anchor = db.query(User).order_by(User.id).first()
    lock_record(db, anchor, conflict_detail="账号正在更新，请刷新后重试")
    db.refresh(admin)
    if not admin.is_active or not has_permission(
        admin, capability, default=admin.role == "admin"
    ):
        raise HTTPException(status_code=403, detail="管理员权限已变更，请重新登录")


def _ensure_active_admin_remains(
    db: Session, user: User, *, role=None, is_active=None
) -> None:
    next_role = user.role if role is None else role
    next_active = user.is_active if is_active is None else is_active
    if (
        user.is_active
        and user.role == "admin"
        and not (next_active and next_role == "admin")
    ):
        remaining = (
            db.query(User.id)
            .filter(User.id != user.id, User.role == "admin", User.is_active.is_(True))
            .first()
        )
        if remaining is None:
            raise HTTPException(
                status_code=400,
                detail="必须保留至少一个启用的管理员账号，请先完成管理员交接",
            )


@router.put("/{user_id}", response_model=dict)
@route_permission('system.users.manage')
def update_user(
    user_id: str,
    data: UserUpdate,
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    capability = "system.users.manage"
    if not has_permission(admin, capability, default=admin.role == "admin"):
        raise HTTPException(403, "没有该人员维护权限")
    _lock_account_changes(db, admin, capability)
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.refresh(u)
    if admin.role != "admin" and (
        u.role == "admin" or (data.role is not None and data.role != u.role)
    ):
        raise HTTPException(403, "只有系统管理员可以调整角色或维护管理员账号")
    _ensure_active_admin_remains(db, u, role=data.role, is_active=data.is_active)
    before = _audit_fields(u)
    if u.username == "admin" and data.is_active is False:
        raise HTTPException(status_code=400, detail="不能停用内置管理员账号")
    if data.is_active is False and u.is_active:
        u.token_version = (u.token_version or 0) + 1
    fields = ["display_name", "role", "phone", "email", "is_active"]
    for f in fields:
        v = getattr(data, f)
        if v is not None:
            setattr(u, f, v)
    if data.password:
        u.password_hash = pwd_context.hash(data.password)
        u.token_version = (u.token_version or 0) + 1
    detail = f"更新用户「{u.display_name}」" + ("（重置密码）" if data.password else "")
    log_change(
        db, None, "user", u.id, "update", admin.id, detail, before, _audit_fields(u)
    )
    db.commit()
    db.refresh(u)
    return _user_dict(u)


@router.delete("/{user_id}")
@route_permission('system.users.manage')
def delete_user(
    user_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    _lock_account_changes(db, admin)
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.refresh(u)
    if admin.role != "admin" and u.role == "admin":
        raise HTTPException(403, "只有系统管理员可以停用管理员账号")
    _ensure_active_admin_remains(db, u, is_active=False)
    if u.username == "admin":
        raise HTTPException(status_code=400, detail="不能删除内置管理员账号")
    before = _audit_fields(u)
    # Soft delete
    if u.is_active:
        u.token_version = (u.token_version or 0) + 1
    u.is_active = False
    log_change(
        db,
        None,
        "user",
        u.id,
        "update",
        admin.id,
        f"停用用户「{u.display_name}」",
        before,
        _audit_fields(u),
    )
    db.commit()
    return {"message": "用户已停用"}


@router.get("/all-active", response_model=list)
@route_permission_exempt('业务候选目录，处理器按可见项目裁剪最小字段')
def list_active_users(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """For project member assignment dropdowns（PM 添加成员/指派执行人需要）。

    v1.2.1 收紧：
    - 现场角色（worker/intern/technician）只返回同项目成员，避免拿到整个组织账号；
    - 全部角色只返回最小字段（id/display_name/role），不下发手机号/邮箱/登录名。
    """
    from app.models import Project

    users = (
        db.query(User).filter(User.is_active == True).order_by(User.display_name).all()
    )
    if user.role in ("worker", "intern", "technician"):
        member_ids = set()
        from app.services.scope import visible_projects

        for p in visible_projects(db, user):
            if user.id in (p.members or []):
                member_ids.update(p.members or [])
                if p.manager:
                    member_ids.add(p.manager)
        member_ids.add(user.id)
        users = [u for u in users if u.id in member_ids]
    return [{"id": u.id, "display_name": u.display_name, "role": u.role} for u in users]
