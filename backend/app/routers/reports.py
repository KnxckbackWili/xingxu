"""Project report routes: weekly/monthly auto-generated reports."""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services.scope import ensure_project_visible
from app.services.reports import generate_project_report

router = APIRouter(tags=["报告"])


@router.get("/projects/{project_id}/report")
@route_permission('project.read')
def project_report(
    project_id: str,
    period: str = Query(default="week", pattern="^(week|month)$"),
    ref_date: Optional[date] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Auto-generated weekly/monthly report — all data from daily work."""
    p = ensure_project_visible(db, project_id, user)
    result=generate_project_report(db,p,period,ref_date,user=user)
    db.commit()
    return result
