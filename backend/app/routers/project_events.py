"""Project milestone writes require project-update authority; arrival writes require plan authority."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import ProjectEvent, User, VehicleUnit
from app.services.change_log import log_change
from app.services.permissions import authorize_project, C_UPDATE, C_PLAN
from app.services.record_lock import lock_writable_project
from app.services.scope import ensure_project_visible
from app.services.optimistic import bump_version
from app.services.project_events import (
    EventKey, event_state, event_dict, events_for_project, set_actual, set_actual_date, sync_arrival_all,
)

router = APIRouter(prefix="/projects", tags=["关键事件"])


class EventUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    planned_date: date | None = None
    actual_at: AwareDatetime | None = None
    actual_date: date | None = None
    note: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=1000)
    version: int | None = None

    @model_validator(mode='after')
    def one_precision(self):
        if self.actual_at is not None and self.actual_date is not None:
            raise ValueError('实际日期与实际时间只能选择一种精度')
        return self


class ArrivalUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    unit_ids: list[str] = Field(min_length=1, max_length=500)
    arrived_at: date | None
    reason: str = Field(default="", max_length=1000)
    version: int | None = None


def _writable(db, project_id, user, capability):
    project = ensure_project_visible(db, project_id, user)
    project = lock_writable_project(db, project, user)
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    authorize_project(user, project, capability)
    return project


@router.get("/{project_id}/events")
@route_permission("project.read")
def list_events(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = ensure_project_visible(db, project_id, user)
    return event_state(db, project)


@router.put("/{project_id}/events/{event_key}")
@route_permission("project.update")
def update_event(project_id: str, event_key: EventKey, body: EventUpdate,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _writable(db, project_id, user, C_UPDATE)
    fields = body.model_fields_set & {"planned_date", "actual_at", "actual_date", "note"}
    if not fields:
        raise HTTPException(400, "请提供要修改的事件字段")
    if event_key == "arrival_all" and "actual_at" in fields:
        raise HTTPException(400, "全部到场实际日期由逐台到场自动汇总，请到车辆页登记")
    row = db.query(ProjectEvent).filter_by(project_id=project_id, event_key=event_key).first()
    before = event_dict(project, event_key, row)
    if row is None:
        row = ProjectEvent(project_id=project_id, event_key=event_key)
        db.add(row)
        db.flush()
    if "actual_date" in fields:
        set_actual_date(db, project, row, body.actual_date, user.id, body.reason)
    elif "actual_at" in fields:
        set_actual(db, project, row, body.actual_at, user.id, body.reason)
    if "planned_date" in fields:
        row.planned_date = body.planned_date
    if "note" in fields:
        row.note = body.note.strip()
    bump_version(project, body.version, db=db)
    after = event_dict(project, event_key, row)
    log_change(db, project_id, "project_event", row.id, "update", user.id,
               f"修改{after['label']}关键事件" + (f"；理由：{body.reason.strip()}" if body.reason.strip() else ""), before, after)
    from app.services.project_documents import materialize_static
    materialize_static(db, project, actor_id=user.id)
    db.commit()
    return {**after, "version": project.version}


@router.put("/{project_id}/vehicle-arrivals")
@route_permission("project.manage_plan")
def update_arrivals(project_id: str, body: ArrivalUpdate,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _writable(db, project_id, user, C_PLAN)
    ids = set(body.unit_ids)
    units = db.query(VehicleUnit).filter(VehicleUnit.project_id == project_id, VehicleUnit.id.in_(ids)).all()
    if len(units) != len(ids):
        raise HTTPException(404, "所选车辆档案不存在或不属于当前项目，未修改任何到场日期")
    if body.arrived_at is None and any(unit.arrived_at is not None for unit in units) and not body.reason.strip():
        raise HTTPException(400, "清除已登记的到场日期必须填写理由")
    bump_version(project, body.version, db=db)
    for unit in units:
        before = unit.arrived_at.isoformat() if unit.arrived_at else None
        unit.arrived_at = body.arrived_at
        log_change(db, project_id, "vehicle_unit", unit.id, "arrival", user.id,
                   f"登记车辆{unit.asset_code}到场日期" + (f"；理由：{body.reason.strip()}" if body.reason.strip() else ""),
                   {"arrived_at": before}, {"arrived_at": body.arrived_at.isoformat() if body.arrived_at else None})
    summary = sync_arrival_all(db, project, user.id, body.reason.strip() or "逐台到场登记")
    from app.services.document_deadlines import refresh_project
    refresh_project(db,project,actor_id=user.id)
    db.commit()
    return {"updated": len(units), "arrival_summary": summary, "events": events_for_project(db, project), "version": project.version}
