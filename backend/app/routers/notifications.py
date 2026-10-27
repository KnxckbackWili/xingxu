"""Notification routes + helper for creating notifications."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import User, Notification, Project, Issue
from sqlalchemy import or_
from app.services.notify import notify  # noqa: F401  (re-exported for legacy imports)

router = APIRouter(tags=["通知"])


def _own_notifications(db: Session, user: User):
    return db.query(Notification).filter(Notification.user_id == user.id)


def _visible_notifications(db, user, rows):
    from app.models import ProjectDocument, DocumentVersion, Attachment
    from app.services.project_documents import can_read_document, can_read_file
    from app.services.scope import visible_project_ids
    visible=None
    result=[]
    for notification in rows:
        if notification.ntype in {'document_submitted','document_reviewed'}:
            if visible is None:visible=set(visible_project_ids(db,user))
            document=db.get(ProjectDocument,notification.entity_id)
            project=db.get(Project,notification.project_id) if notification.project_id in visible else None
            if project is None or document is None or document.project_id!=project.id or not can_read_document(user,project,document):continue
            versions=db.query(DocumentVersion).filter_by(project_document_id=document.id)
            if any((asset:=db.get(Attachment,version.attachment_id)) is None or not can_read_file(user,project,asset) for version in versions):continue
        result.append(notification)
    return result


@router.get("/notifications")
@route_permission('personal.messages.use')
def list_notifications(
    limit: int = 50,
    offset: int = Query(default=0, ge=0),
    unread_only: bool = False,
    ntype: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = _own_notifications(db, user)
    if unread_only:
        q = q.filter(Notification.is_read == False)  # noqa: E712
    if ntype:
        q = q.filter(Notification.ntype == ntype)
    visible = _visible_notifications(db,user,q.order_by(Notification.created_at.desc(), Notification.id.desc()).all())
    items = visible[offset:offset+limit] if limit>=0 else visible[offset:]
    from app.services.project_documents import audit_access
    from app.models import ProjectDocument, DocumentVersion, Attachment
    for item in items:
        if item.ntype in {'document_submitted','document_reviewed'}:
            document=db.get(ProjectDocument,item.entity_id);project=db.get(Project,item.project_id)
            if document is not None and project is not None:
                files=[db.get(Attachment,version.attachment_id) for version in db.query(DocumentVersion).filter_by(project_document_id=document.id)]
                audit_access(db,project,user,documents=[document],files=[asset for asset in files if asset is not None])
    db.commit()
    # 老指派通知把上报人写成内部ID。只修复系统字段与原问题上报人精确一致的记录。
    issue_types = {"issue_assigned", "issue_reported"}
    issue_ids = {n.entity_id for n in items if n.ntype in issue_types and n.entity_id}
    reporters = dict(db.query(Issue.id, Issue.reporter_id).filter(Issue.id.in_(issue_ids)).all()) if issue_ids else {}
    reporter_ids = {value for value in reporters.values() if value}
    names = dict(db.query(User.id, User.display_name).filter(User.id.in_(reporter_ids)).all()) if reporter_ids else {}

    def display_content(n):
        reporter_id = reporters.get(n.entity_id)
        suffix = f" · 上报人：{reporter_id}"
        if n.ntype in issue_types and reporter_id and n.content.startswith("严重程度：") and n.content.endswith(suffix):
            return f"{n.content[:-len(suffix)]} · 上报人：{names.get(reporter_id, '已删除用户')}"
        return n.content

    return [
        {
            "id": n.id,
            "title": n.title,
            "content": display_content(n),
            "ntype": n.ntype,
            "project_id": n.project_id,
            "entity_id": n.entity_id,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in items
    ]


@router.get("/notifications/unread-count")
@route_permission('personal.messages.use')
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = len(_visible_notifications(db,user,_own_notifications(db, user).filter(
        Notification.is_read == False,  # noqa: E712
    ).all()))
    return {"count": count}


@router.post("/notifications/{notification_id}/read")
@route_permission('personal.messages.use')
def mark_read(notification_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        return {"message": "通知不存在"}
    n.is_read = True
    db.commit()
    return {"message": "已标记为已读"}


@router.post("/notifications/read-all")
@route_permission('personal.messages.use')
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,  # noqa: E712
    ).update({"is_read": True})
    db.commit()
    return {"message": "全部已读"}


class BatchRead(BaseModel):
    ids: List[str]


@router.post("/notifications/read-batch")
@route_permission('personal.messages.use')
def mark_batch_read(data: BatchRead, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Batch mark own notifications as read (others' ids are ignored)."""
    n = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.id.in_(data.ids),
    ).update({"is_read": True})
    db.commit()
    return {"updated": n}
