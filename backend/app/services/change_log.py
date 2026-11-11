"""Write one line of the history. Call inside the transaction of the change itself."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ChangeLog, User


def log_change(db: Session, project_id: Optional[str], kind: str, row_id: str, action: str,
               user: "User | str | None", detail: str = "", old_value=None, new_value=None, *,
               field: str = "", row_label: str = ""):
    if isinstance(user, str):
        user = db.get(User, user)
    db.add(ChangeLog(project_id=project_id, kind=kind, row_id=str(row_id or "")[:64], action=action,
                     user_id=user.id if user else None, user_name=user.display_name if user else "系统",
                     detail=detail, old_value=old_value, new_value=new_value, field=field,
                     row_label=(row_label or "")[:300]))
