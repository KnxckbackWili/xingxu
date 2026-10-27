"""人员不可用时段与跨项目安排查询服务。

排程服务（下一任务：任务排班优化的负载均衡指派）直接复用本模块：
- 不可用时段查询：某人某天是否可用 / 时段列表 / 未来安排汇总
- 跨项目当日排班汇总：分配冲突检测（其他项目是否已排满）
"""

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User, UserUnavailability


def get_user_unavailability(
    db: Session,
    user_id: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list:
    """某人的不可用时段列表（可按日期范围裁剪）。"""
    q = db.query(UserUnavailability).filter(UserUnavailability.user_id == user_id)
    if from_date:
        q = q.filter(UserUnavailability.end_date >= from_date)
    if to_date:
        q = q.filter(UserUnavailability.start_date <= to_date)
    return q.order_by(UserUnavailability.start_date).all()


def get_unavailability_on(
    db: Session, user_id: str, day: date
) -> Optional[UserUnavailability]:
    """覆盖某天的不可用时段（含当天），无则 None。"""
    return (
        db.query(UserUnavailability)
        .filter(
            UserUnavailability.user_id == user_id,
            UserUnavailability.start_date <= day,
            UserUnavailability.end_date >= day,
        )
        .order_by(UserUnavailability.start_date)
        .first()
    )


def is_available_on(db: Session, user_id: str, day: date) -> bool:
    """某人某天是否可用（没有覆盖当天的不可用时段）。"""
    return get_unavailability_on(db, user_id, day) is None


def unavailability_dict(u: UserUnavailability, user_name: str = "") -> dict:
    return {
        "id": u.id,
        "user_id": u.user_id,
        "user_name": user_name,
        "start_date": u.start_date.isoformat(),
        "end_date": u.end_date.isoformat(),
        "reason": u.reason or "",
        "note": u.note or "",
        "created_by": u.created_by,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def unavailability_for_viewer(
    db: Session,
    viewer: User,
    record: UserUnavailability,
    user_name: str = "",
) -> dict:
    """Keep staffing dates visible without widening access to personal details.

    Shared calendars and assignment checks may need the unavailable dates, but
    they must not reveal a peer's private reason, note or audit metadata when
    the dedicated personnel endpoint would deny that viewer access.
    """
    target = db.get(User, record.user_id)
    if target is not None and can_view_user(viewer, target, db):
        return unavailability_dict(record, user_name)
    return {
        "user_id": record.user_id,
        "user_name": user_name,
        "start_date": record.start_date.isoformat(),
        "end_date": record.end_date.isoformat(),
    }


def unavailability_map_on(db: Session, user_ids: list, day: date) -> dict:
    """某天不可用的人员映射 {user_id: UserUnavailability}（排程指派批量查询用）。"""
    if not user_ids:
        return {}
    rows = (
        db.query(UserUnavailability)
        .filter(
            UserUnavailability.user_id.in_(user_ids),
            UserUnavailability.start_date <= day,
            UserUnavailability.end_date >= day,
        )
        .all()
    )
    return {r.user_id: r for r in rows}


def currently_unavailable_count(
    db: Session, user_ids: list, day: Optional[date] = None
) -> int:
    """某天处于不可用状态的人数（按人去重）。"""
    day = day or date.today()
    rows = (
        db.query(UserUnavailability.user_id)
        .filter(
            UserUnavailability.user_id.in_(user_ids),
            UserUnavailability.start_date <= day,
            UserUnavailability.end_date >= day,
        )
        .all()
    )
    return len({row[0] for row in rows})


def upcoming_unavailability(
    db: Session,
    user_ids: list,
    days: int = 30,
    *,
    viewer: Optional[User] = None,
) -> list:
    """未来 days 天内（含今天）的不可用安排，供人员看板「近期不可用」使用。"""
    today = date.today()
    end = today + timedelta(days=days)
    rows = (
        (
            db.query(UserUnavailability)
            .filter(
                UserUnavailability.user_id.in_(user_ids),
                UserUnavailability.start_date <= end,
                UserUnavailability.end_date >= today,
            )
            .order_by(UserUnavailability.start_date)
            .all()
        )
        if user_ids
        else []
    )
    names = (
        {
            u.id: u.display_name
            for u in db.query(User).filter(User.id.in_(user_ids)).all()
        }
        if user_ids
        else {}
    )
    if viewer is not None:
        return [
            unavailability_for_viewer(db, viewer, u, names.get(u.user_id, ""))
            for u in rows
        ]
    return [unavailability_dict(u, names.get(u.user_id, "")) for u in rows]


def can_view_user(user: User, target: User, db: Session) -> bool:
    """当前用户是否为本人，或具备人员可用性管理权限。"""
    if user.id == target.id:
        return True
    from app.services.system_permissions import has_permission

    if has_permission(
        user, "system.availability.manage", default=user.role in ("admin", "pm")
    ):
        return True
    return False
