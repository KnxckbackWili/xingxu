"""What is still missing, per project. These five rules are the only ones in the system."""
from collections import defaultdict

from sqlalchemy.orm import Session

from app import models


def _rows(db: Session, model, project_ids, *conditions):
    if not project_ids:
        return []
    return (db.query(model).filter(model.project_id.in_(project_ids), model.deleted_at.is_(None), *conditions)
            .order_by(model.created_at, model.id).all())


def project_gaps(db: Session, projects) -> dict:
    """project id -> the five gap lists, for the given live projects."""
    ids = [project.id for project in projects]
    steps, vehicles, marks = defaultdict(list), defaultdict(list), defaultdict(set)
    for step in sorted(_rows(db, models.ProjectStep, ids), key=lambda row: row.sort_order):
        steps[step.project_id].append(step)
    for vehicle in sorted(_rows(db, models.Vehicle, ids), key=lambda row: row.sort_order):
        vehicles[vehicle.project_id].append(vehicle)
    if ids:
        for mark in db.query(models.VehicleMark).filter(models.VehicleMark.project_id.in_(ids)):
            marks[mark.vehicle_id].add(mark.step_id)
    with_files = {owner for (owner,) in db.query(models.File.owner_id).filter(
        models.File.project_id.in_(ids), models.File.owner_kind == "document", models.File.deleted_at.is_(None))} if ids else set()
    work, issues, documents, items = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for row in sorted(_rows(db, models.WorkItem, ids, models.WorkItem.done.is_(False)), key=lambda row: row.sort_order):
        work[row.project_id].append({"id": row.id, "stage": row.stage, "name": row.name})
    for row in _rows(db, models.Issue, ids, models.Issue.is_closed.is_(False)):
        issues[row.project_id].append({"id": row.id, "name": row.description})
    for row in sorted(_rows(db, models.Document, ids), key=lambda row: row.sort_order):
        if row.id not in with_files:
            documents[row.project_id].append({"id": row.id, "name": row.name})
    for row in sorted(_rows(db, models.Item, ids, models.Item.arrived.is_(False)), key=lambda row: row.sort_order):
        items[row.project_id].append({"id": row.id, "name": row.name})
    result = {}
    for project_id in ids:
        unfinished = []
        for vehicle in vehicles[project_id]:
            missing = [step.name for step in steps[project_id] if step.id not in marks[vehicle.id]]
            if missing:
                unfinished.append({"id": vehicle.id, "name": vehicle.vehicle_no, "fleet_no": vehicle.fleet_no, "missing": missing})
        result[project_id] = {
            "vehicles": {"total": len(vehicles[project_id]), "missing": unfinished},
            "work": work[project_id], "issues": issues[project_id],
            "documents": documents[project_id], "items": items[project_id]}
    return result
