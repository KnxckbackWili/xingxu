"""Resolve post-purge cache provenance using the surviving encrypted receipt."""
import json
from app import models


def purged_snapshot(db,project_id):
    from app.services.project_deletion import verified_backup,backup_zip
    from app.services.project_permanent_deletion import fingerprint
    receipts=db.query(models.ProjectPermanentBackup).filter_by(project_id=project_id).filter(
        models.ProjectPermanentBackup.purged_at.isnot(None)).order_by(models.ProjectPermanentBackup.prepared_at.desc()).all()
    for receipt in receipts:
        try:
            with backup_zip(verified_backup(receipt)) as archive:snapshot=json.loads(archive.read('project-backup.json'))
            if fingerprint(snapshot)==receipt.content_sha256:return snapshot
        except (OSError,ValueError,KeyError):continue
    return None


def contains_removal(snapshot,identity,metadata):
    from app.services.file_retention import manifest_removal
    for item in snapshot['binary_files']['manifest']:
        if (item.get('removal_record_ids') or {}).get(metadata.get('attachment_id'))!=identity:continue
        if (item.get('stored_name'),item.get('sha256'),item.get('size'))!=(metadata.get('stored_name'),metadata.get('sha256'),metadata.get('size')):continue
        if manifest_removal(snapshot,item):return True
    return False
