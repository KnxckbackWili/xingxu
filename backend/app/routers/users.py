"""Accounts. Two kinds only: administrators and employees."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import User
from app.routers.auth import pwd_context
from app.services.change_log import log_change

router = APIRouter(prefix="/users", tags=["账号"])
ROLES = ("admin", "employee")


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_.@-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: str = "employee"


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


def _out(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role,
            "is_active": user.is_active, "created_at": user.created_at.isoformat() + "Z"}


def _other_active_admin(db: Session, user: User) -> bool:
    return db.query(User.id).filter(User.role == "admin", User.is_active.is_(True), User.id != user.id).first() is not None


@router.get("")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_out(user) for user in db.query(User).order_by(User.created_at, User.username)]


@router.get("/names")
def names(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everyone may see who the colleagues are (the history filter and the avatars need it)."""
    return [{"id": user.id, "display_name": user.display_name, "is_active": user.is_active}
            for user in db.query(User).order_by(User.display_name)]


@router.post("")
def create_user(body: UserCreate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.role not in ROLES:
        raise HTTPException(400, "账号类型只能是系统管理员或员工")
    if db.query(User.id).filter(User.username == body.username).first():
        raise HTTPException(400, f"用户名 {body.username} 已存在")
    user = User(username=body.username, display_name=body.display_name.strip(), role=body.role,
                password_hash=pwd_context.hash(body.password))
    db.add(user)
    db.flush()
    log_change(db, None, "user", user.id, "create", actor, "新建账号", new_value={"username": user.username, "role": user.role},
               row_label=user.display_name)
    db.commit()
    return _out(user)


@router.put("/{user_id}")
def update_user(user_id: str, body: UserUpdate, actor: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None:
        raise HTTPException(404, "账号不存在")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("role") is not None and changes["role"] not in ROLES:
        raise HTTPException(400, "账号类型只能是系统管理员或员工")
    loses_admin = (changes.get("role", user.role) != "admin" or changes.get("is_active", user.is_active) is False)
    if user.role == "admin" and user.is_active and loses_admin and not _other_active_admin(db, user):
        raise HTTPException(400, "至少要保留一个启用中的系统管理员")
    if user.id == actor.id and changes.get("is_active") is False:
        raise HTTPException(400, "不能停用自己的账号")
    old = {}
    for name in ("display_name", "role", "is_active"):
        if changes.get(name) is not None and changes[name] != getattr(user, name):
            old[name] = getattr(user, name)
            setattr(user, name, changes[name].strip() if name == "display_name" else changes[name])
    if changes.get("password"):
        user.password_hash = pwd_context.hash(changes["password"])
        old["password"] = "已重置"
    if not old:
        return _out(user)
    # A stopped, demoted or reset account loses every session it already had.
    if {"is_active", "role", "password"} & set(old):
        user.token_version = (user.token_version or 0) + 1
    log_change(db, None, "user", user.id, "update", actor, "修改账号",
               old_value={key: value for key, value in old.items() if key != "password"},
               new_value={key: ("已重置" if key == "password" else getattr(user, key)) for key in old},
               row_label=user.display_name)
    db.commit()
    return _out(user)
