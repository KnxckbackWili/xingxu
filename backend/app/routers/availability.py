"""Personnel unavailability with explicit management permissions and owner privacy.

Writes use global change_log audit records. Availability management permission
or ownership controls access to detailed unavailability reasons.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission, route_permission_contextual
from app.db import get_db
from app.deps import get_current_user, require_pm
from app.models import User, UserUnavailability
from app.services import availability as avail
from app.services.change_log import log_change

router = APIRouter(tags=["人员可用性"])


class UnavailabilityCreate(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(default="其他", max_length=100)
    note: str = Field(default="", max_length=500)


class UnavailabilityUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reason: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=500)


def _get_user_or_404(db: Session, user_id: str) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return u


def _validate_period(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")


@router.get("/users/{user_id}/unavailability")
@route_permission_contextual('system.availability.manage', reason='处理器按本人或可用性管理权限决定详细资料可见性')
def list_unavailability(
    user_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看本人或有明确管理权限的人员不可用时段。"""
    target = _get_user_or_404(db, user_id)
    if not avail.can_view_user(user, target, db):
        raise HTTPException(status_code=403, detail="没有权限查看该人员的可用性")
    items = avail.get_user_unavailability(db, user_id)
    return [avail.unavailability_dict(u) for u in items]


@router.post("/users/{user_id}/unavailability")
@route_permission('system.availability.manage')
def create_unavailability(
    user_id: str,
    data: UnavailabilityCreate,
    user: User = Depends(require_pm),
    db: Session = Depends(get_db),
):
    """登记不可用时段（admin/PM）。"""
    target = _get_user_or_404(db, user_id)
    _validate_period(data.start_date, data.end_date)
    reason = (data.reason or "其他").strip() or "其他"
    u = UserUnavailability(
        user_id=user_id,
        start_date=data.start_date,
        end_date=data.end_date,
        reason=reason,
        note=data.note or "",
        created_by=user.id,
    )
    db.add(u)
    db.flush()
    log_change(
        db,
        None,
        "user",
        user_id,
        "create",
        user.id,
        f"登记人员不可用：{target.display_name} {data.start_date}~{data.end_date}（{reason}）",
    )
    db.commit()
    db.refresh(u)
    return avail.unavailability_dict(u, target.display_name)


@router.put("/users/{user_id}/unavailability/{unavail_id}")
@route_permission('system.availability.manage')
def update_unavailability(
    user_id: str,
    unavail_id: str,
    data: UnavailabilityUpdate,
    user: User = Depends(require_pm),
    db: Session = Depends(get_db),
):
    """修改不可用时段（admin/PM）。"""
    _get_user_or_404(db, user_id)
    u = db.get(UserUnavailability, unavail_id)
    if u is None or u.user_id != user_id:
        raise HTTPException(status_code=404, detail="不可用时段不存在")
    # Partial edits must be validated against the latest complete interval.
    # Otherwise two concurrent, individually valid start/end edits can leave
    # start_date > end_date and silently make the person available on every day.
    from app.services.record_lock import lock_record

    lock_record(db, u, conflict_detail="不可用时段正由另一操作更新，请刷新后重试")
    start_date = data.start_date if data.start_date is not None else u.start_date
    end_date = data.end_date if data.end_date is not None else u.end_date
    _validate_period(start_date, end_date)
    if data.start_date is not None:
        u.start_date = data.start_date
    if data.end_date is not None:
        u.end_date = data.end_date
    if data.reason is not None:
        u.reason = (data.reason or "其他").strip() or "其他"
    if data.note is not None:
        u.note = data.note
    db.flush()
    log_change(
        db,
        None,
        "user",
        user_id,
        "update",
        user.id,
        f"修改人员不可用时段：{u.start_date}~{u.end_date}（{u.reason}）",
    )
    db.commit()
    db.refresh(u)
    return avail.unavailability_dict(u)


@router.delete("/users/{user_id}/unavailability/{unavail_id}")
@route_permission('system.availability.manage')
def delete_unavailability(
    user_id: str,
    unavail_id: str,
    user: User = Depends(require_pm),
    db: Session = Depends(get_db),
):
    """删除不可用时段（admin/PM）。"""
    _get_user_or_404(db, user_id)
    u = db.get(UserUnavailability, unavail_id)
    if u is None or u.user_id != user_id:
        raise HTTPException(status_code=404, detail="不可用时段不存在")
    detail = f"删除人员不可用时段：{u.start_date}~{u.end_date}（{u.reason}）"
    db.delete(u)
    db.flush()
    log_change(db, None, "user", user_id, "delete", user.id, detail)
    db.commit()
    return {"message": "不可用时段已删除"}
