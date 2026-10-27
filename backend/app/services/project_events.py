"""Milestone dates and complete-fleet arrival aggregation, within the caller's transaction."""
from collections import Counter
from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.models import Project, ProjectEvent, Vehicle, VehicleUnit
from app.services.change_log import log_change

EventKey = Literal["internal_kickoff", "ship", "arrival_all", "delivery_signed", "commissioning_done", "go_live", "training_done", "acceptance", "handover"]
DispatchPlatform = Literal["NDC", "GRACE", "integrated"]
EVENT_LABELS = {
    "internal_kickoff": "内部启动会", "ship": "发车", "arrival_all": "全部到场",
    "delivery_signed": "到货签收", "commissioning_done": "调试完工", "go_live": "上线运行",
    "training_done": "培训完成", "acceptance": "项目验收", "handover": "交付售后",
}


class EventPlanInput(BaseModel):
    """New writes have one date source; legacy dates remain available for reading."""
    event_plans: dict[EventKey, date | None] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_date(cls, value):
        if isinstance(value, dict) and "planned_entry_date" in value:
            raise ValueError("planned_entry_date 已只读，请通过 event_plans.ship 修改计划发车日期")
        return value


def iso_utc(value: datetime | None):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def normalize_actual(value: datetime | None):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value else None


def event_dict(project: Project, key: str, row: ProjectEvent | None):
    actual = row.actual_at if row else None
    derived = key == "arrival_all"
    return {
        "id": row.id if row else None, "event_key": key, "label": EVENT_LABELS[key],
        "planned_date": row.planned_date.isoformat() if row and row.planned_date else None,
        "actual_at": iso_utc(actual), "recorded_by": row.recorded_by if row else None,
        "note": row.note or "" if row else "", "derived": derived,
        "actual_precision": "date" if derived or row and row.actual_date else "datetime",
        "actual_date": row.actual_date.isoformat() if row and row.actual_date else (actual.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(project.timezone or "Asia/Shanghai")).date().isoformat()
                        if actual and derived else None),
        "actual_source": row.actual_source if row else None,
        "source_description": "按逐台到场日期汇总" if derived else (row.actual_source or {}).get("time_basis", "人工登记实际时间") if row else "未登记",
    }


def events_for_project(db: Session, project: Project, event_rows=None):
    if event_rows is None:
        event_rows = db.query(ProjectEvent).filter_by(project_id=project.id).all()
    rows = {row.event_key: row for row in event_rows}
    return [event_dict(project, key, rows.get(key)) for key in EVENT_LABELS]


def event_state(db: Session, project: Project):
    return {"events": events_for_project(db, project), "arrival_summary": arrival_summary(db, project.id),
            "version": project.version, "timezone": project.timezone, "dispatch_platform": project.dispatch_platform}


def planned_event_date(db: Session, project_id: str, key="ship"):
    return db.query(ProjectEvent.planned_date).filter_by(project_id=project_id, event_key=key).scalar()


def update_plans(db: Session, project: Project, plans: dict, actor_id: str):
    for key, value in plans.items():
        row = db.query(ProjectEvent).filter_by(project_id=project.id, event_key=key).first()
        if (row.planned_date if row else None) == value:
            continue
        if row is None:
            row = ProjectEvent(project_id=project.id, event_key=key)
            db.add(row)
            db.flush()
        before = row.planned_date.isoformat() if row.planned_date else None
        row.planned_date = value
        log_change(db, project.id, "project_event", row.id, "plan", actor_id,
                   f"修改{EVENT_LABELS[key]}计划日期", {"planned_date": before},
                   {"planned_date": value.isoformat() if value else None})

    from app.services.document_deadlines import refresh_project
    refresh_project(db,project,actor_id=actor_id,generate=False)


def arrival_summary(db: Session, project_id: str):
    vehicles = db.query(Vehicle).filter_by(project_id=project_id).all()
    units = db.query(VehicleUnit).filter_by(project_id=project_id).all()
    expected = {v.id: v.quantity for v in vehicles}
    registered = Counter(unit.vehicle_id for unit in units)
    complete = bool(expected) and bool(units) and all(count > 0 and registered.get(key, 0) == count for key, count in expected.items()) and not (registered.keys() - expected.keys())
    dates = [unit.arrived_at for unit in units if unit.arrived_at is not None]
    return {
        "expected": sum(expected.values()), "registered": len(units), "arrived": len(dates),
        "registry_complete": complete,
        "all_arrived_date": max(dates) if complete and len(dates) == len(units) else None,
    }


def sync_arrival_all(db: Session, project: Project, actor_id: str, reason: str):
    """Never infer the complete fleet from a partial registry or from lifecycle stage."""
    db.flush()
    summary = arrival_summary(db, project.id)
    arrival_date = summary["all_arrived_date"]
    actual = (datetime.combine(arrival_date, time.min, ZoneInfo(project.timezone or "Asia/Shanghai"))
              .astimezone(timezone.utc).replace(tzinfo=None)) if arrival_date else None
    row = db.query(ProjectEvent).filter_by(project_id=project.id, event_key="arrival_all").first()
    if (row.actual_at if row else None) == actual:
        from app.services.document_deadlines import refresh_project
        refresh_project(db,project,actor_id=actor_id,generate=False)
        return summary
    if row is None:
        row = ProjectEvent(project_id=project.id, event_key="arrival_all")
        db.add(row)
        db.flush()
    before = event_dict(project, "arrival_all", row)
    row.actual_at = actual
    row.recorded_by = actor_id
    log_change(db, project.id, "project_event", row.id, "derive", actor_id,
               f"按逐台到场日期汇总全部到场：{reason}；计划{summary['expected']}台、建档{summary['registered']}台、到场{summary['arrived']}台",
               before, event_dict(project, "arrival_all", row))
    from app.services.document_deadlines import refresh_project
    refresh_project(db,project,actor_id=actor_id,generate=False)
    return summary


def set_actual(db: Session, project: Project, row: ProjectEvent, actual: datetime | None,
               actor_id: str, reason: str):
    if row.event_key == "arrival_all":
        raise HTTPException(400, "全部到场实际日期由逐台到场自动汇总，请到车辆页登记")
    if (row.actual_at is not None or row.actual_date is not None) and actual is None and not reason.strip():
        raise HTTPException(400, "清除已发生时间必须填写理由")
    row.actual_at = normalize_actual(actual)
    row.actual_date = None
    row.actual_source = {"kind": "manual", "time_basis": "人工登记实际时间"} if actual else None
    row.recorded_by = actor_id


def set_actual_date(db, project, row, actual, actor_id, reason):
    if row.event_key == 'arrival_all':
        raise HTTPException(400, '全部到场日期由逐台到场汇总')
    if actual is None:
        return set_actual(db, project, row, None, actor_id, reason)
    if actual > datetime.now(ZoneInfo(project.timezone or 'Asia/Shanghai')).date():
        raise HTTPException(400, '实际发生日期不能晚于项目当地今天')
    row.actual_at = None
    row.actual_date = actual
    row.actual_source = {'kind': 'manual_date', 'time_basis': '人工登记实际日期，仅精确到日'}
    row.recorded_by = actor_id


def record_document_dates(db, project, document_ids, attachment_id, dates, actor_id, *, pending_ids=()):
    """Only explicit business dates on the exact submitted sign-off can mark an event."""
    from app.models import ProjectDocument, DocumentVersion
    allowed = {'internal_kickoff', 'delivery_signed', 'commissioning_done', 'go_live', 'training_done', 'acceptance', 'handover'}
    if not dates:
        return
    if len(dates) > 7 or any(key not in allowed for key in dates):
        raise HTTPException(400, '签单日期包含不支持的事件')
    documents = db.query(ProjectDocument).filter(ProjectDocument.project_id == project.id, ProjectDocument.id.in_(document_ids)).all()
    modified = False
    for key, day in dates.items():
        eligible = [document for document in documents if document.timing_event == key and document.scope == 'project'
                    and document.timing_type in ('after_event', 'after_milestone') and document.status == 'submitted']
        if not eligible:
            raise HTTPException(400, f'{EVENT_LABELS[key]}日期必须关联本次提交的对应签单资料')
        versions = []
        for document in eligible:
            version = db.query(DocumentVersion).filter_by(project_document_id=document.id).order_by(DocumentVersion.uploaded_at.desc().nullslast(), DocumentVersion.id.desc()).first()
            if version is None or version.attachment_id != attachment_id:
                raise HTTPException(409, '签单版本已变化，请重新读取后登记')
            versions.append(version.id)
        if day > datetime.now(ZoneInfo(project.timezone or 'Asia/Shanghai')).date():
            raise HTTPException(400, '签单实际发生日期不能晚于项目当地今天')
        row = db.query(ProjectEvent).filter_by(project_id=project.id, event_key=key).first()
        if row is None:
            row = ProjectEvent(project_id=project.id, event_key=key)
            db.add(row); db.flush()
        known_date = row.actual_date or (row.actual_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(project.timezone or 'Asia/Shanghai')).date() if row.actual_at else None)
        if known_date is not None:
            if known_date != day:
                raise HTTPException(409, '签单日期与已登记发生时间不一致；请负责人先核对并明确更正关键事件')
            continue
        before = event_dict(project, key, row)
        row.actual_date = day
        modified = True
        row.actual_source = {'kind': 'document_signature', 'attachment_id': attachment_id, 'document_version_ids': versions,
                             'time_basis': '签单明确记录的实际日期，仅精确到日'}
        row.recorded_by = actor_id
        log_change(db, project.id, 'project_event', row.id, 'signature', actor_id, f'按签单登记{EVENT_LABELS[key]}实际日期', before, event_dict(project, key, row))
    if modified:
        from app.services.optimistic import bump_version
        from app.services.project_documents import materialize_static
        bump_version(project, project.version, db=db)
        materialize_static(db, project)
        # The explicit business date belongs to this same submission. Capture
        # its deadline before freezing newly submitted facts, but never move a
        # deadline that was already submitted before this request.
        from app.services.document_deadlines import calculate
        events = {row.event_key: row for row in db.query(ProjectEvent).filter_by(project_id=project.id)}
        units = {row.id: row for row in db.query(VehicleUnit).filter_by(project_id=project.id)}
        for document in documents:
            if document.id not in pending_ids or document.timing_event not in dates:
                continue
            deadline = calculate(document, project, events, units)
            before = {'due_at': iso_utc(document.due_at), 'estimated': document.due_is_estimated, 'basis': document.due_basis}
            after = {'due_at': iso_utc(deadline.due_at), 'estimated': deadline.estimated, 'basis': deadline.basis}
            if before != after:
                bump_version(document, document.version, db=db)
                document.due_at, document.due_is_estimated, document.due_basis = deadline.due_at, deadline.estimated, deadline.basis
                log_change(db, project.id, 'project_document', document.id, 'deadline', actor_id,
                           '按本次签单明确的实际日期保存提交截止', before, after)
