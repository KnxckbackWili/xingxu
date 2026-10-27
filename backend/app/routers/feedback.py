"""系统问题反馈（HYPE-72）。

- 提交：所有登录用户（任何角色）均可提交，必填问题描述、可选复现步骤；
  系统自动记录提交人（user_id）、提交时间（created_at）与处理状态（初始 pending）。
- 读取与跟踪：管理角色（admin/director/pm）可读取反馈列表与详情，并更新处理状态。
  普通用户只能提交——列表/详情/状态更新接口对非管理角色一律 403，杜绝横向越权读取。
- 数据库迁移：feedback 表由 init_db 的 create_all 幂等创建（新建表无需 ALTER，
  容器重启数据仍保留在数据库中）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import Feedback, User, FEEDBACK_STATUSES

router = APIRouter(prefix="/feedback", tags=["系统问题反馈"])

# 管理角色：管理员（admin）+ 项目管理（director 全局治理、pm 项目管理层）
MANAGE_ROLES = ("admin", "director", "pm")
require_feedback_manage = require_roles(*MANAGE_ROLES)

MAX_DESCRIPTION_LEN = 2000
MAX_STEPS_LEN = 5000


class FeedbackCreate(BaseModel):
    model_config = {"extra": "forbid"}

    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LEN)
    steps: str = Field(default="", max_length=MAX_STEPS_LEN)


class FeedbackStatusUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    status: str


def _user_names(db: Session, user_ids: set) -> dict:
    """批量解析反馈提交人的 display_name。"""
    ids = [uid for uid in user_ids if uid]
    if not ids:
        return {}
    rows = db.query(User).filter(User.id.in_(ids)).all()
    return {u.id: u.display_name for u in rows}


def _feedback_dict(fb: Feedback, names: Optional[dict] = None) -> dict:
    return {
        "id": fb.id,
        "description": fb.description,
        "steps": fb.steps,
        "status": fb.status,
        "user_id": fb.user_id,
        "user_name": (names or {}).get(fb.user_id, ""),
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
        "updated_at": fb.updated_at.isoformat() if fb.updated_at else None,
    }


@router.post("")
@route_permission('feedback.submit')
def create_feedback(
    body: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任何已登录用户提交问题反馈（必填描述 + 可选复现步骤）。"""
    description = body.description.strip()
    if not description:
        raise HTTPException(status_code=422, detail="问题描述不能为空")
    fb = Feedback(
        user_id=user.id,
        description=description,
        steps=(body.steps or "").strip(),
        status="pending",
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return _feedback_dict(fb, {user.id: user.display_name})


@router.get("")
@route_permission('system.feedback.manage')
def list_feedback(
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_feedback_manage),
    db: Session = Depends(get_db),
):
    """管理角色读取反馈列表（分页 + 按处理状态筛选）。"""
    if status is not None and status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=422, detail="无效的处理状态")
    q = db.query(Feedback)
    if status:
        q = q.filter(Feedback.status == status)
    total = q.count()
    items = (
        q.order_by(Feedback.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    names = _user_names(db, {i.user_id for i in items})
    return {
        "items": [_feedback_dict(i, names) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{feedback_id}")
@route_permission('system.feedback.manage')
def get_feedback(
    feedback_id: str,
    user: User = Depends(require_feedback_manage),
    db: Session = Depends(get_db),
):
    """管理角色读取反馈详情。"""
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return _feedback_dict(fb, _user_names(db, {fb.user_id}))


@router.patch("/{feedback_id}/status")
@route_permission('system.feedback.manage')
def update_feedback_status(
    feedback_id: str,
    body: FeedbackStatusUpdate,
    user: User = Depends(require_feedback_manage),
    db: Session = Depends(get_db),
):
    """管理角色更新反馈处理状态（pending/processing/done）。"""
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if body.status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=422, detail="无效的处理状态")
    fb.status = body.status
    db.commit()
    db.refresh(fb)
    return _feedback_dict(fb, _user_names(db, {fb.user_id}))
