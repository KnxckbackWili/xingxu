"""Change log routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import User, ChangeLog

router = APIRouter(tags=["变更记录"])


@router.get("/projects/{project_id}/logs", response_model=list)
@route_permission('project.read', 'system.audit.read')
def list_logs(
    project_id: str,
    limit: int = Query(default=200, le=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_access: bool = Query(default=False),
):
    """List change logs for a project (newest first)."""
    from app.services.scope import ensure_project_visible
    project=ensure_project_visible(db, project_id, user)
    query = db.query(ChangeLog).filter(ChangeLog.project_id == project_id)
    if include_access is not True:
        # Every visit to a confidential page records a view; leave those out unless the reader asks for them.
        query = query.filter(ChangeLog.action.notin_(('confidential_view', 'confidential_dl', 'confidential_export')))
    logs = (
        query
        .order_by(ChangeLog.created_at.desc())
        .limit(limit)
        .all()
    )
    from app.services.project_documents import can_read_document, can_read_definition, can_read_file
    from app.models import ProjectDocument, ProjectDocumentDefinition, Attachment, DocumentVersion
    def allowed(log):
        if log.entity_type=='project_document':
            row=db.get(ProjectDocument,log.entity_id)
            return row is None or can_read_document(user,project,row)
        if log.entity_type=='project_document_definition':
            row=db.get(ProjectDocumentDefinition,log.entity_id)
            return row is None or can_read_definition(user,project,row)
        if log.entity_type=='attachment':
            row=db.get(Attachment,log.entity_id)
            return row is None or can_read_file(user,project,row)
        if log.entity_type=='document_version':
            row=db.get(DocumentVersion,log.entity_id)
            if row is None:return True
            document=db.get(ProjectDocument,row.project_document_id);asset=db.get(Attachment,row.attachment_id)
            return document is not None and asset is not None and can_read_document(user,project,document) and can_read_file(user,project,asset)
        return True
    logs=[log for log in logs if allowed(log)]
    # Resolve operator names
    op_ids = {l.operator_id for l in logs if l.operator_id}
    op_names = {}
    if op_ids:
        for u in db.query(User).filter(User.id.in_(op_ids)).all():
            op_names[u.id] = u.display_name
    from app.services.field_operations import text_redactor
    redact=text_redactor(db,project,user)
    return [
        {
            "id": l.id,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "action": l.action,
            "operator_id": l.operator_id,
            "operator_name": op_names.get(l.operator_id, "未知"),
            "detail": redact(l.detail or ""),
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]
