"""Immutable audit retention, deliberately separate from new-project JSON import.

This includes original business identities and evidence state. It is not an import
format and excludes account credentials, private AI chats, and personal memories.
Binary files are not embedded; the manifest keeps their storage ownership and
hashes. Full system backup remains necessary to recover from storage loss.
"""
from datetime import date, datetime
from pathlib import Path
import hashlib

from app import models
from app.config import UPLOAD_DIR


# Explicit business allowlist prevents a new project-linked private/security
# table from silently being copied into administrator-visible audit archives.
RETAINED_MODELS = (
    models.ProjectMember, models.ProjectEvent, models.Vehicle, models.VehicleUnit, models.VehicleLifecycleEvent,
    models.ProjectVehicleStep, models.VehicleProgress, models.VehicleProgressMigration,
    models.ProjectInventoryItem, models.ProjectInventoryMovement, models.ItemApplication,
    models.Phase, models.Module, models.Task, models.VehicleCheckDefinition, models.CheckItem, models.ScheduleEntry,
    models.DailyProgress, models.WeeklyPlanCell, models.Issue,
    models.Attachment, models.ArchiveChecklist, models.AcceptanceRecord,
    models.FieldOperation,
    models.ProjectDocumentDefinition, models.ProjectDocument, models.DocumentNoticeReceipt, models.ProjectReportReceipt,
    models.UploadSession,models.UploadChunk,models.FileCleanupReceipt,models.FileRemovalRecord,
    models.DocumentTriggerEvent,models.IssueSlaReceipt,
    models.ProjectPreparationItem, models.ProjectReadinessReview,
)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _row(row):
    return {column.key: _json_value(getattr(row, column.key)) for column in row.__table__.columns}


def project_retention_snapshot(db, project):
    from sqlalchemy import and_, or_
    records = {}
    task_ids = db.query(models.Task.id).filter(models.Task.project_id == project.id)
    phase_ids = db.query(models.Module.phase_id).filter(models.Module.project_id == project.id)
    actor_ids = {project.created_by, project.manager, project.technical_manager, *(project.members or [])}
    from app.services.file_retention import removal_record
    removed={}
    files = {}
    for model in RETAINED_MODELS:
        owned = model.project_id == project.id
        if model is models.CheckItem:
            # Legacy execution checks may predate the redundant project_id.
            # The task is the authoritative parent; never sweep another
            # project's explicitly-owned checks into this archive.
            owned = and_(model.task_id.in_(task_ids), or_(model.project_id == project.id, model.project_id.is_(None)))
        elif model is models.Phase:
            # Older project modules legitimately reference shared template
            # phases. Keep those definitions along with project-local phases.
            owned = or_(owned, and_(model.id.in_(phase_ids), model.project_id.is_(None)))
        rows = db.query(model).filter(owned).order_by(model.id).all()
        records[model.__tablename__] = [_row(row) for row in rows]
        for row in rows:
            for column in model.__table__.columns:
                if any(fk.target_fullname == 'users.id' for fk in column.foreign_keys):
                    actor_ids.add(getattr(row, column.key))
            if isinstance(row, models.Attachment):
                files.setdefault(row.stored_name, {'stored_name': row.stored_name, 'filename': row.filename, 'references': []})['references'].append({'table': 'attachments', 'id': row.id})
                record=removal_record(row,db)
                if record is not None:removed[row.id]=record
            elif isinstance(row, models.Task):
                for ref in row.reference_docs or []:
                    if isinstance(ref, dict) and ref.get('stored_name'):
                        stored = ref['stored_name']
                        files.setdefault(stored, {'stored_name': stored, 'filename': ref.get('filename', ''), 'references': []})['references'].append({'table': 'tasks', 'id': row.id})
    document_ids = [row.id for row in db.query(models.ProjectDocument).filter_by(project_id=project.id)]
    versions = db.query(models.DocumentVersion).filter(models.DocumentVersion.project_document_id.in_(document_ids)).order_by(models.DocumentVersion.id).all()
    records['document_versions'] = [_row(row) for row in versions]
    actor_ids.update(row.uploaded_by for row in versions if row.uploaded_by)
    blank_ids = {row.blank_file_id for model in (models.ProjectDocumentDefinition,models.ProjectDocument)
                 for row in db.query(model).filter_by(project_id=project.id) if row.blank_file_id}
    blanks = db.query(models.DocumentTemplateFile).filter(models.DocumentTemplateFile.id.in_(blank_ids)).order_by(models.DocumentTemplateFile.id).all()
    records['document_template_files'] = [_row(row) for row in blanks]
    for blank in blanks:
        files.setdefault(blank.stored_name, {'stored_name':blank.stored_name,'filename':blank.filename,'references':[]})['references'].append({'table':'document_template_files','id':blank.id})
        if blank.uploaded_by:actor_ids.add(blank.uploaded_by)
    for stored, item in files.items():
        references=item['references']
        if references and all(ref['table']=='attachments' and ref['id'] in removed for ref in references):
            record=removed[references[0]['id']]
            item.update(intentionally_removed=True,available_at_purge=False,sha256=record.sha256,size=record.file_size,
                removal_record_ids={ref['id']:removed[ref['id']].id for ref in references},
                byte_recovery='历史原字节已按明确授权策略清理；本备份只保留完整元数据与清理凭据')
            continue
        path = UPLOAD_DIR / stored
        safe = isinstance(stored, str) and Path(stored).name == stored and UPLOAD_DIR.resolve() in path.resolve().parents
        item['available_at_purge'] = bool(safe and path.is_file())
        if item['available_at_purge']:
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(block)
            item['sha256'] = digest.hexdigest()
            item['size'] = path.stat().st_size
    actor_ids.discard(None)
    actors = [{'id': user.id, 'display_name': user.display_name, 'role': user.role}
              for user in db.query(models.User).filter(models.User.id.in_(actor_ids)).order_by(models.User.id).all()]
    return {
        'type': 'agvpm-project-retention', 'version': 1,
        'project': _row(project), 'modules': records['modules'], 'records': records, 'actors': actors,
        'binary_files': {'included': False, 'retained_in_uploads': True, 'recovery': 'Original files remain owned by this archive; full system backup is required for storage recovery. JSON alone does not contain file bytes.',
                         'manifest': [files[key] for key in sorted(files)]},
        'restore_supported': False,
    }


def is_retained_file(db, stored_name: str) -> bool:
    """A retained archive remains an owner after live Attachment rows are gone."""
    for (snapshot,) in db.query(models.ProjectArchive.snapshot).yield_per(50):
        for item in (snapshot or {}).get('binary_files', {}).get('manifest', []):
            if isinstance(item, dict) and item.get('stored_name') == stored_name:
                return True
    return False
