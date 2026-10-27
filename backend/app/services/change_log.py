from typing import Optional

"""Helper for writing change log entries."""

from sqlalchemy.orm import Session
from app.models import ChangeLog


def log_change(
    db: Session,
    project_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    operator_id: Optional[str],
    detail: str,
    old_value=None,
    new_value=None,
):
    """Write a single change-log entry. Call inside a transaction."""
    db.add(ChangeLog(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        operator_id=operator_id,
        detail=detail,
        old_value=old_value,
        new_value=new_value,
    ))
