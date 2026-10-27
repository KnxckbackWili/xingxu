"""通知渠道管理员配置 API（HYPE-58：管理员专用「通知渠道」入口）。

- 全部端点仅 admin（403 给其他角色）。
- GET 只返回 configured/掩码/来源/最近测试结果，绝不含 Webhook query 或 Secret 明文。
- PUT/停用/测试发送：env 托管时只读（409）；测试发送走独立限流 + 结果审计。
- 测试发送是直接同步外发，不经过 outbox，不产生/重复业务通知，也不影响站内通知事务。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.deps import require_admin
from app.models import User
from app.services import channel_settings
from app.services.rate_limit import rate_limit
from app.db import get_db

router = APIRouter(tags=["通知渠道"])


def _detail(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


@router.get("/notification-channels")
@route_permission('system.notifications.configure')
def get_channels(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return channel_settings.get_status(db)


class DingtalkConfigBody(BaseModel):
    enabled: bool
    webhook_url: str = ""
    secret: str | None = None      # None/缺省 = 保留现有 Secret；非空 = 覆盖
    clear_secret: bool = False     # 显式清除已保存的 Secret


@router.put("/notification-channels/dingtalk")
@route_permission('system.notifications.configure')
def put_dingtalk(body: DingtalkConfigBody, user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    try:
        result = channel_settings.save_dingtalk(
            db, user.id, enabled=body.enabled,
            webhook_url=body.webhook_url, secret=body.secret,
            clear_secret=body.clear_secret,
        )
    except PermissionError as error:
        raise _detail(409, str(error))
    except ValueError as error:
        raise _detail(400, str(error))
    return result


@router.delete("/notification-channels/dingtalk")
@route_permission('system.notifications.configure')
def disable_dingtalk(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        channel_settings.disable_dingtalk(db, user.id)
    except PermissionError as error:
        raise _detail(409, str(error))
    return {"message": "钉钉渠道已停用（配置保留，站内通知不受影响）"}


@router.post("/notification-channels/dingtalk/test")
@route_permission('system.notifications.configure')
def test_dingtalk(user: User = Depends(require_admin),
                  _: None = Depends(rate_limit(limit=channel_settings._TEST_RATE_LIMIT,
                                               window=channel_settings._TEST_RATE_WINDOW)),
                  db: Session = Depends(get_db)):
    """发送测试通知（管理员手动触发，须前端二次确认后调用）。"""
    return channel_settings.send_test_dingtalk(db, user.id)
