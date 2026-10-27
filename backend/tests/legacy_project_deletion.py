"""Build old-version rows for history/purge compatibility tests only."""
from app.db import SessionLocal
from app.models import Project, ProjectGovernanceRequest
from app.time_utils import utcnow
from app.services.change_log import log_change


def legacy_pending_delete(client, headers, project_id, reason="历史删除申请"):
    actor_id = client.get("/api/auth/me", headers=headers).json()["id"]
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        row = ProjectGovernanceRequest(project_id=project_id, project_name=project.name,
            requested_by=actor_id, source_manager_id=project.manager,
            request_type="delete", reason=reason)
        db.add(row); db.commit()
        return {"id": row.id, "project_id": project_id}


def legacy_soft_delete(client, headers, project_id):
    actor_id = client.get("/api/auth/me", headers=headers).json()["id"]
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        project.deleted_at = utcnow()
        log_change(db, project.id, "project", project.id, "delete", actor_id,
                   "旧版本审批软删除历史数据")
        db.commit()


def legacy_archive_snapshot(db, project):
    """Test-only pre-v3 archive fixture; the application has no new archive writer."""
    from app.models import ProjectArchive, ChangeLog
    from app.services.project_retention import project_retention_snapshot, _row
    from app.routers.archives import _archive_checksum
    from app.time_utils import utcnow
    logs = [_row(row) for row in db.query(ChangeLog).filter_by(project_id=project.id).order_by(ChangeLog.created_at)]
    archive = ProjectArchive(project_id=project.id, project_name=project.name,
        snapshot=project_retention_snapshot(db, project), change_logs=logs,
        actor_ids=sorted({row['operator_id'] for row in logs if row['operator_id']}), purged_at=utcnow(), checksum='pending')
    archive.checksum = _archive_checksum(archive)
    db.add(archive); db.flush()
    return archive
