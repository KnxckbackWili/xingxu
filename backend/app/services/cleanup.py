"""Empty the trash: rows and projects deleted more than TRASH_DAYS ago are removed for good."""
import shutil
from datetime import timedelta

from sqlalchemy.orm import Session

from app import models
from app.config import TRASH_DAYS, UPLOAD_DIR
from app.services import files as storage
from app.time_utils import utcnow

_PROJECT_ROWS = (models.VehicleMark, models.VehicleRecord, models.Issue, models.Vehicle, models.ProjectStep,
                 models.WorkItem, models.Document, models.Item, models.File)


def purge_project(db: Session, project: models.Project) -> None:
    for model in _PROJECT_ROWS:
        db.query(model).filter(model.project_id == project.id).delete(synchronize_session=False)
    db.delete(project)
    db.flush()
    folder = (UPLOAD_DIR / project.id)
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder, ignore_errors=True)


def _purge_files(db: Session, query) -> int:
    count = 0
    for row in query.all():
        storage.discard(row.storage_path)
        db.delete(row)
        count += 1
    return count


def purge_expired(db: Session, now=None) -> dict:
    cutoff = (now or utcnow()) - timedelta(days=TRASH_DAYS)
    removed = {"projects": 0, "rows": 0, "files": 0}
    for project in db.query(models.Project).filter(models.Project.deleted_at < cutoff).all():
        purge_project(db, project)
        removed["projects"] += 1
    removed["files"] += _purge_files(db, db.query(models.File).filter(models.File.deleted_at < cutoff))
    for model, owner_kind in ((models.Document, "document"), (models.Issue, "issue")):
        for row in db.query(model).filter(model.deleted_at < cutoff).all():
            removed["files"] += _purge_files(db, db.query(models.File).filter_by(owner_kind=owner_kind, owner_id=row.id))
            db.delete(row)
            removed["rows"] += 1
    for model in (models.VehicleRecord, models.WorkItem, models.Item, models.TemplateRow):
        removed["rows"] += db.query(model).filter(model.deleted_at < cutoff).delete(synchronize_session=False)
    for vehicle in db.query(models.Vehicle).filter(models.Vehicle.deleted_at < cutoff).all():
        db.query(models.VehicleMark).filter_by(vehicle_id=vehicle.id).delete(synchronize_session=False)
        db.query(models.VehicleRecord).filter_by(vehicle_id=vehicle.id).delete(synchronize_session=False)
        db.query(models.Issue).filter_by(vehicle_id=vehicle.id).update({"vehicle_id": None}, synchronize_session=False)
        db.delete(vehicle)
        removed["rows"] += 1
    for step in db.query(models.ProjectStep).filter(models.ProjectStep.deleted_at < cutoff).all():
        db.query(models.VehicleMark).filter_by(step_id=step.id).delete(synchronize_session=False)
        db.delete(step)
        removed["rows"] += 1
    for template in db.query(models.Template).filter(models.Template.deleted_at < cutoff).all():
        db.query(models.TemplateRow).filter_by(template_id=template.id).delete(synchronize_session=False)
        db.delete(template)
        removed["rows"] += 1
    db.commit()
    return removed
