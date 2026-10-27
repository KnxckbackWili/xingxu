"""Notification creation helper (shared by routers and scheduled jobs)."""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app import config
from app.models import Notification, NotificationOutbox, Project
from app.services.notify_channels import channels_enabled_db


def notify(
    db: Session,
    user_id: str,
    title: str,
    content: str = "",
    ntype: str = "system",
    project_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    channels: bool = True,
) -> None:
    """Create an in-app notification plus an outbox row for async external delivery.

    HYPE-58：事务内只落库（站内通知 + notification_outbox 出站队列），绝不在此发起
    外部 HTTP 请求；外发由独立 scheduler 进程 deliver_outbox 按批投递（超时/重试/
    指数退避/幂等键）。未配置任何外部渠道时队列行直接标记 disabled，避免无限积压。
    失败既不回滚主业务，也不会重复生成站内通知。
    """
    project = db.get(Project, project_id) if project_id else None
    notification = Notification(
        user_id=user_id,
        title=title,
        content=content,
        ntype=ntype,
        project_id=project_id,
        entity_id=entity_id,
    )
    db.add(notification)
    db.flush()
    db.add(
        NotificationOutbox(
            notification_id=notification.id,
            user_id=user_id,
            title=title,
            content=content,
            ntype=ntype,
            project_id=project_id,
            idempotency_key=str(uuid.uuid4()),
            status="pending" if channels and channels_enabled_db(db) else "disabled",
            max_attempts=getattr(config, "NOTIFY_RETRY_MAX_ATTEMPTS", 3),
        )
    )
