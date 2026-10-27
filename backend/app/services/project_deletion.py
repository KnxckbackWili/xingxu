"""Project-only, recoverable deletion. Files are durable before the DB commit.

This is evidence and storage protection, not new-project import or whole-DB
restore: restoring simply makes the original project and rows visible again.
"""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
from contextlib import contextmanager

from app.services import backup_crypto as codec
from app.services.system_permissions import has_permission

from fastapi import HTTPException
from app import config, models
from app.models.project_deletion import ProjectDeletionRecord
from app.services.change_log import log_change
from app.time_utils import utcnow
from app.services.permissions import (
    authorize_project,
    project_capabilities,
    C_DELETE,
    C_EXPORT,
)
from app.services.project_retention import project_retention_snapshot, _row
from app.services.record_lock import lock_record
from app.services.scope import ensure_project_visible
from app.services.optimistic import bump_version


def backup_directory():
    directory = config.DATA_DIR / "project-deletion-backups"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (
        directory.is_symlink()
        or directory.resolve().parent != config.DATA_DIR.resolve()
    ):
        raise OSError("unsafe backup directory")
    directory.chmod(0o700)
    return directory


def _backup_path(name):
    if (
        not isinstance(name, str)
        or "\\" in name
        or Path(name).name != name
        or not name.endswith((".zip", ".zip.agvenc"))
    ):
        raise OSError("unsafe backup name")
    path = backup_directory() / name
    if path.is_symlink() or path.resolve().parent != backup_directory().resolve():
        raise OSError("unsafe backup path")
    return path


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _upload_path(stored):
    if (
        not isinstance(stored, str)
        or not stored
        or "\\" in stored
        or Path(stored).name != stored
    ):
        raise OSError("unsafe file reference")
    path = config.UPLOAD_DIR / stored
    if path.is_symlink() or path.resolve().parent != config.UPLOAD_DIR.resolve():
        raise OSError("unsafe project file")
    return path


def project_backup_snapshot(db, project, *, include_deletion_snapshots=False):
    # Validate before the legacy retention helper reads any path. Missing evidence
    # is a backup failure, never an excuse to discard the project.
    assets=db.query(models.Attachment).filter_by(project_id=project.id).all()
    from app.services.file_retention import removal_record
    required_names={row.stored_name for row in assets if removal_record(row,db) is None}
    stored_names = {
        row.stored_name
        for row in db.query(models.Attachment).filter_by(project_id=project.id)
    }
    for task in db.query(models.Task).filter_by(project_id=project.id):
        for ref in task.reference_docs or []:
            if isinstance(ref, dict) and ref.get("stored_name"):
                stored_names.add(ref["stored_name"])
                required_names.add(ref['stored_name'])
    blank_ids={row.blank_file_id for model in (models.ProjectDocumentDefinition,models.ProjectDocument)
               for row in db.query(model).filter_by(project_id=project.id) if row.blank_file_id}
    stored_names.update(row.stored_name for row in db.query(models.DocumentTemplateFile).filter(models.DocumentTemplateFile.id.in_(blank_ids)))
    required_names.update(row.stored_name for row in db.query(models.DocumentTemplateFile).filter(models.DocumentTemplateFile.id.in_(blank_ids)))
    for stored in stored_names:
        source=_upload_path(stored)
        if stored in required_names and not source.is_file():
            raise OSError("missing project file")
    snapshot = project_retention_snapshot(db, project)
    # Project-scoped planning preferences and complete edit/audit history are
    # not part of the older immutable-purge allowlist.
    for model in (
        models.ProjectGovernanceRequest,
        models.ExternalShare,
        models.ExternalAccessLog,
        models.ProjectSchedulePolicy,
        models.TaskDurationOverride,
        models.ProjectCreationReceipt,
        models.OfflineOpReceipt,
    ):
        snapshot["records"][model.__tablename__] = [
            _row(row)
            for row in db.query(model)
            .filter_by(project_id=project.id)
            .order_by(*model.__table__.primary_key.columns)
        ]
    snapshot["records"]["change_logs"] = [
        _row(row)
        for row in db.query(models.ChangeLog)
        .filter_by(project_id=project.id)
        .order_by(models.ChangeLog.id)
    ]
    actors = {item["id"] for item in snapshot["actors"]}
    for table, field in (
        ("change_logs", "operator_id"),
        ("project_schedule_policies", "updated_by"),
        ("task_duration_overrides", "updated_by"),
    ):
        actors.update(
            row[field] for row in snapshot["records"][table] if row.get(field)
        )
    snapshot["actors"] = [
        {"id": row.id, "display_name": row.display_name, "role": row.role}
        for row in db.query(models.User)
        .filter(models.User.id.in_(actors))
        .order_by(models.User.id)
    ]
    snapshot.update(
        type="agvpm-project-deletion-backup",
        version=1,
        restore_supported=True,
        recovery="还原原项目ID和保留的业务数据；此包不授予新项目验收或执行资格。",
    )
    snapshot["binary_files"].update(
        included=True, recovery="所有未按策略清理的项目原件字节随包保存；已授权清理的历史原字节只保留完整元数据与清理凭据，不含系统密钥或个人私有事项。"
    )
    snapshot['records']['project_deletion_records'] = [
        {key: value for key, value in _row(row).items() if include_deletion_snapshots or key != 'snapshot'}
        for row in db.query(ProjectDeletionRecord).filter_by(project_id=project.id).order_by(ProjectDeletionRecord.id)
    ]
    return snapshot


def create_project_backup(db, project, deletion_id, *, permanent=False):
    snapshot = project_backup_snapshot(db, project, include_deletion_snapshots=permanent)
    path = _backup_path(f"{deletion_id}.zip.agvenc")
    password = codec.get_passphrase(config.DATA_DIR)
    published = False
    try:
        with codec.encrypted_writer(path, password) as output, ZipFile(output, 'w', ZIP_DEFLATED) as bundle:
            for item in snapshot['binary_files']['manifest']:
                if item.get('intentionally_removed'):
                    from app.services.file_retention import manifest_removal
                    if not manifest_removal(snapshot,item):raise OSError('invalid file removal evidence')
                    continue
                source = _upload_path(item['stored_name'])
                entry = 'files/' + item['stored_name']
                digest, size = hashlib.sha256(), 0
                with source.open('rb') as stream, bundle.open(entry, 'w', force_zip64=True) as target:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        target.write(block); digest.update(block); size += len(block)
                item.update(path=entry, size=size, sha256=digest.hexdigest(), available_at_purge=True)
            bundle.writestr('project-backup.json', json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode('utf-8'))
        published = True
        return snapshot, path, _digest(path), path.stat().st_size
    except Exception:
        if published: path.unlink(missing_ok=True)
        raise


def verified_backup_path(record):
    path = _backup_path(record.backup_name)
    if not path.is_file() or path.stat().st_size != record.backup_bytes or _digest(path) != record.backup_sha256:
        raise OSError('backup checksum mismatch')
    return path


@contextmanager
def backup_zip(path):
    # Historical plaintext stays untouched; plaintext from new envelopes is only
    # yielded after GCM authentication in a private 0700/0600 temporary scope.
    if codec.is_encrypted(path):
        with codec.decrypted_file(path, codec.get_passphrase(config.DATA_DIR)) as plain, ZipFile(plain) as bundle:
            yield bundle
    else:
        with ZipFile(path) as bundle:
            yield bundle


def verified_backup(record):
    path = verified_backup_path(record)
    with backup_zip(path) as bundle:
        if bundle.testzip() is not None:
            raise OSError('backup CRC mismatch')
        snapshot = json.loads(bundle.read('project-backup.json'))
        if snapshot.get('project', {}).get('id') != record.project_id or snapshot.get('type') != 'agvpm-project-deletion-backup':
            raise OSError('wrong project backup')
        for item in snapshot['binary_files']['manifest']:
            if item.get('intentionally_removed'):
                from app.services.file_retention import manifest_removal
                if not manifest_removal(snapshot,item):raise OSError('invalid file removal evidence')
                continue
            digest, size = hashlib.sha256(), 0
            with bundle.open(item['path']) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block); size += len(block)
            if size != item['size'] or digest.hexdigest() != item['sha256']:
                raise OSError('project file checksum mismatch')
    return path


def backup_available(record):
    try:
        verified_backup_path(record)
        return True
    except Exception:
        return False


def _authorized_locked_project(db, project_id, user, *, deleted=False):
    project = ensure_project_visible(db, project_id, user, include_deleted=deleted)
    authorize_project(user, project, C_DELETE)
    lock_record(db, project, conflict_detail="项目正由另一操作更新，请刷新后重试")
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    project = ensure_project_visible(db, project_id, user, include_deleted=deleted)
    authorize_project(user, project, C_DELETE)
    if deleted and project.deleted_at is None:
        raise HTTPException(409, "项目已还原，请刷新回收站")
    return project


def delete_project(db, project_id, user, version=None, reason=""):
    project = _authorized_locked_project(db, project_id, user)
    if version is None:
        raise HTTPException(400, "请重新读取项目并携带版本号确认删除")
    if version is not None and version != (project.version or 0):
        raise HTTPException(409, "项目已被修改，请刷新后重新确认删除")
    deletion_id = str(uuid4())
    try:
        snapshot, path, digest, size = create_project_backup(db, project, deletion_id)
    except Exception:
        db.rollback()
        raise HTTPException(500, "删除前项目备份失败，项目未删除") from None
    try:
        bump_version(project, version, db=db)
        when = utcnow()
        record = ProjectDeletionRecord(
            id=deletion_id,
            project_id=project.id,
            deleted_by=user.id,
            deleted_at=when,
            status_before_delete=project.status,
            reason=reason.strip(),
            snapshot=snapshot,
            backup_name=path.name,
            backup_sha256=digest,
            backup_bytes=size,
            protected_from_purge=True,
        )
        db.add(record)
        project.deleted_at = when
        log_change(
            db,
            project.id,
            "project",
            project.id,
            "delete",
            user.id,
            "项目已备份并移入回收站",
            new_value={
                "deletion_id": deletion_id,
                "reason": reason.strip(),
                "backup_sha256": digest,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return {
        "message": "项目已备份并移入回收站",
        "deletion_id": deletion_id,
        "project_id": project.id,
        "version": project.version,
        "backup": {"available": True, "sha256": digest, "bytes": size},
    }


def restore_project(db, project_id, user, *, version, deletion_id):
    project = _authorized_locked_project(db, project_id, user, deleted=True)
    record = db.get(ProjectDeletionRecord, deletion_id)
    if (
        record is None
        or record.project_id != project.id
        or record.restored_at is not None
        or record.deleted_at != project.deleted_at
    ):
        raise HTTPException(409, "删除记录已变化，请刷新回收站后重新确认")
    if version != (project.version or 0):
        raise HTTPException(409, "项目已被修改，请刷新回收站后重新确认")
    legacy_unbacked = not record.backup_name
    try:
        if legacy_unbacked:
            project_backup_snapshot(db, project)  # all remaining file references must be intact
        else:
            verified_backup(record)
    except Exception:
        raise HTTPException(409, '项目备份或现存文件校验失败，项目未还原，请联系管理员') from None
    # Missing original files can be repaired from this project's verified ZIP.
    # An existing different file is a conflict: never overwrite silently.
    created = []
    try:
        with backup_zip(verified_backup(record)) if not legacy_unbacked else _empty_backup() as bundle:
            evidence = json.loads(bundle.read("project-backup.json")) if bundle else {"binary_files": {"manifest": []}}
            for item in evidence["binary_files"]["manifest"]:
                if item.get('intentionally_removed'):
                    from app.services.file_retention import manifest_removal
                    if not manifest_removal(evidence,item):raise OSError('invalid file removal evidence')
                    continue
                destination = _upload_path(item["stored_name"])
                if destination.exists():
                    if (
                        not destination.is_file()
                        or _digest(destination) != item["sha256"]
                    ):
                        raise HTTPException(
                            409,
                            "项目文件与删除备份不一致，未覆盖原文件，请联系管理员核对",
                        )
                    continue
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created.append(destination)
                with os.fdopen(fd, "wb") as handle:
                    with bundle.open(item['path']) as source:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            handle.write(block)
                    handle.flush()
                    os.fsync(handle.fileno())
        if created:
            dirfd = os.open(config.UPLOAD_DIR, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        bump_version(project, version, db=db)
        project.deleted_at = None
        record.restored_by, record.restored_at = user.id, utcnow()
        log_change(
            db,
            project.id,
            "project",
            project.id,
            "restore",
            user.id,
            "从回收站还原原项目",
            new_value={"deletion_id": record.id, "recovered_files": len(created)},
        )
        db.commit()
    except Exception as error:
        db.rollback()
        for path in created:
            path.unlink(missing_ok=True)
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(409, "项目文件恢复失败，项目未还原，请联系管理员") from None
    from app.services.cache import cache_clear

    cache_clear("dashboard:")
    return {
        "message": "项目已还原",
        "project_id": project.id,
        "version": project.version,
    }


def recycle_item(db, project, record, *, user):
    actor = db.get(models.User, record.deleted_by) if record.deleted_by else None
    available = backup_available(record)
    return {
        "id": project.id,
        "name": project.name,
        "status_before_delete": record.status_before_delete,
        "deleted_at": record.deleted_at.isoformat(),
        "deleted_by_name": actor.display_name if actor else "原操作人已不存在",
        "deletion_id": record.id,
        "version": project.version,
        "delete_backup_available": available,
        "can_restore": available or (not record.backup_name),
        "can_download_backup": available
        and C_EXPORT in project_capabilities(user, project),
        "can_permanently_delete": user.role == "admin"
        and C_EXPORT in project_capabilities(user, project)
        and has_permission(user, 'system.projects.purge', default=True),
        "reason": record.reason,
        "backup": {
            "available": available,
            "sha256": record.backup_sha256,
            "bytes": record.backup_bytes,
            "scope": "仅此项目的业务记录和项目文件；不含系统密钥或个人私有事项",
        },
    }


@contextmanager
def _empty_backup():
    yield None
