"""Administrator-only system permission policy editing with optimistic CAS."""
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy.orm import Session
from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.change_log import log_change
from app.services.record_lock import lock_record
from app.services.system_permissions import PERMISSION_KEYS, RETIRED_PERMISSION_KEYS, catalog, default_permissions, effective_permissions

router = APIRouter(prefix="/permissions", tags=["全系统成员权限"])


class PermissionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=0)
    overrides: Dict[str, StrictBool]


def policy_admin(user: User = Depends(get_current_user)):
    # This authority is deliberately not delegatable via require_roles/grants.
    if not user.is_active or user.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以管理全系统权限")
    return user


def user_summary(user):
    return dict(id=user.id, username=user.username, display_name=user.display_name,
                role=user.role, is_active=bool(user.is_active),
                permission_version=int(user.permission_version or 0))


def policy_payload(user):
    values = user.permission_overrides
    overrides = {key: value for key, value in values.items()
                 if key in PERMISSION_KEYS and key != "permission.manage" and type(value) is bool} if isinstance(values, dict) else {}
    return dict(user=user_summary(user), version=int(user.permission_version or 0),
                overrides=overrides, effective=effective_permissions(user),
                defaults=default_permissions(user))


@router.get("/catalog")
@route_permission('permission.manage')
def get_catalog(_: User = Depends(policy_admin)):
    return catalog()


@router.get("/users")
@route_permission('permission.manage')
def permission_users(_: User = Depends(policy_admin), db: Session = Depends(get_db)):
    # This minimal directory stays usable when an administrator denies the
    # separate full personnel-management page to themself.
    return [user_summary(user) for user in db.query(User).order_by(User.display_name, User.id).all()]


@router.get("/users/{user_id}")
@route_permission('permission.manage')
def get_user_policy(user_id: str, _: User = Depends(policy_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return policy_payload(user)


@router.put("/users/{user_id}")
@route_permission('permission.manage')
def set_user_policy(user_id: str, data: PermissionUpdate,
                    actor: User = Depends(policy_admin), db: Session = Depends(get_db)):
    unknown = set(data.overrides) - PERMISSION_KEYS - RETIRED_PERMISSION_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail="包含未知权限项")
    if "permission.manage" in data.overrides:
        raise HTTPException(status_code=422, detail="管理员权限管理入口不能关闭或委派")
    # Same stable anchor as account role/deactivation changes: serialize policy
    # changes with administrator retirement, then refresh the actor's authority.
    anchor = db.query(User).filter(User.username == "admin").first()
    if anchor is None:
        anchor = db.query(User).order_by(User.id).first()
    if anchor is None:
        raise HTTPException(status_code=403, detail="管理员身份已变化，请重新登录")
    detail = "账号权限正由另一操作更新，请重新读取后重试"
    lock_record(db, anchor, conflict_detail=detail)
    db.refresh(actor)
    if not actor.is_active or actor.role != "admin":
        raise HTTPException(status_code=403, detail="管理员身份已变化，请重新登录")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    from app.services.system_permissions import READ_ONLY_ACTIONS
    if target.role == "readonly" and any(allowed and key not in READ_ONLY_ACTIONS for key, allowed in data.overrides.items() if key in PERMISSION_KEYS):
        raise HTTPException(422, "只读预设不能授予写权限，请先在账号设置调整角色")
    # Anchor serializes all policy writers; deterministic order also avoids
    # cross-target lock inversion with other account-maintenance callers.
    for row in sorted({actor.id: actor, target.id: target}.values(), key=lambda row: row.id):
        if row.id != anchor.id:
            lock_record(db, row, conflict_detail=detail)
    db.refresh(actor)
    if not actor.is_active or actor.role != "admin":
        raise HTTPException(status_code=403, detail="管理员身份已变化，请重新登录")
    current_version = int(target.permission_version or 0)
    if data.version != current_version:
        raise HTTPException(status_code=409, detail="权限已被其他操作修改，请重新读取后重试")
    original=target.permission_overrides if isinstance(target.permission_overrides,dict) else {}
    if any(key not in original or original[key]!=data.overrides[key] for key in set(data.overrides)&RETIRED_PERMISSION_KEYS):
        raise HTTPException(422,'退役权限不能新授予或修改；原值仅作历史保全')
    active_overrides={key:value for key,value in data.overrides.items() if key in PERMISSION_KEYS}
    # Full-map editors only own current fields. Preserve inert historical keys,
    # including a stale editor's unchanged retired value, without reactivating it.
    new_overrides={key:value for key,value in original.items() if key not in PERMISSION_KEYS}|active_overrides
    old_overrides = policy_payload(target)["overrides"]
    if original == new_overrides:
        return policy_payload(target)
    target.permission_overrides = new_overrides
    target.permission_version = current_version + 1
    log_change(db, None, "user_permissions", target.id, "update", actor.id,
               "更新成员全系统权限",
               old_value={"version": current_version, "overrides": old_overrides},
               new_value={"version": target.permission_version, "overrides": active_overrides})
    db.commit()
    db.refresh(target)
    return policy_payload(target)


@router.get("/projects/{project_id}/users/{user_id}/reasons")
@route_permission("project.read")
def member_permission_reasons(project_id: str, user_id: str,
                              actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.scope import ensure_project_visible
    from app.services.permissions import authorize_project, C_MEMBERS
    from app.services.permission_explanations import project_permission_reasons

    project = ensure_project_visible(db, project_id, actor)
    if actor.id != user_id and actor.role != "admin":
        authorize_project(actor, project, C_MEMBERS)
    from app.services.scope import active_co_manager
    from app.services.permission_explanations import membership_reasons
    related = user_id in (project.members or []) or user_id in {project.manager, project.technical_manager} or active_co_manager(project, user_id)
    if actor.role != "admin" and actor.id != user_id and not related:
        # Do not even resolve the outsider account: missing, disabled and
        # forbidden accounts must produce the same project-local explanation.
        return membership_reasons(project.id, user_id)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "成员不存在")
    return project_permission_reasons(db, project, target)
