"""Explicit administrator-only permanent deletion after a durable ciphertext receipt."""
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, delete, or_

from app import models
from app.db import Base
from app.models.project_deletion import ProjectDeletionRecord, ProjectPermanentBackup
from app.services.change_log import log_change
from app.services.permissions import authorize_project, C_EXPORT
from app.services.project_deletion import (
    _authorized_locked_project, project_backup_snapshot, create_project_backup,
    verified_backup,
)
from app.services.system_permissions import has_permission
from app.time_utils import utcnow


def require_admin(user):
    if user.role != 'admin' or not user.is_active or not has_permission(user, 'system.projects.purge', default=True):
        raise HTTPException(403, '仅系统管理员可管理项目永久删除备份及永久删除')


def fingerprint(snapshot):
    # ZIP entry paths are derived metadata, not a change to business evidence.
    snapshot = json.loads(json.dumps(snapshot, ensure_ascii=False))
    for item in snapshot['binary_files']['manifest']:
        item.pop('path', None)
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _locked(db, project_id, user, version, deletion_id):
    require_admin(user)
    project = _authorized_locked_project(db, project_id, user, deleted=True)
    db.execute(select(models.User.id).where(models.User.id == user.id).with_for_update()).all()
    db.refresh(user)
    require_admin(user)  # re-evaluated after waiting on both ownership/actor locks
    authorize_project(user, project, C_EXPORT)
    if (project.version or 0) != version:
        raise HTTPException(409, '项目已变化，请重新读取并生成永久删除备份')
    record = db.get(ProjectDeletionRecord, deletion_id)
    if not record or record.project_id != project.id or record.restored_at or record.deleted_at != project.deleted_at:
        raise HTTPException(409, '删除周期已变化，请重新读取回收站')
    # Strong parent key lock blocks FK inserts; lock child rows before sampling
    # the evidence as well. SQLite already holds its database writer lock.
    db.execute(select(models.Project.id).where(models.Project.id == project.id).with_for_update()).all()
    list(_affected_keys(db, project, lock=True))
    if db.query(models.PersonalEvent.id).filter_by(project_id=project.id).first():
        raise HTTPException(409, '项目仍有关联的个人日程，请由所有者改挂后再永久删除；私有日程不会进入项目备份')
    return project


def _affected_keys(db, project, *, lock=False):
    affected = {'projects': [{'id': project.id}]}
    for table in Base.metadata.sorted_tables:
        conditions = []
        for fk in table.foreign_keys:
            parents = affected.get(fk.column.table.name, [])
            if parents:
                values = [row[fk.column.name] for row in parents if fk.column.name in row]
                if len(values) != len(parents):
                    raise HTTPException(409, '存在不能确认备份范围的关联关系，项目未删除')
                conditions.append(fk.parent.in_(values))
        if not conditions:
            continue
        keys = list(table.primary_key.columns)
        query = select(*keys).where(or_(*conditions))
        rows = db.execute(query.with_for_update() if lock else query).all()
        if rows:
            affected[table.name] = [dict(zip([key.name for key in keys], row)) for row in rows]
            yield table, keys, rows


def _snapshot(db, project):
    snapshot = project_backup_snapshot(db, project, include_deletion_snapshots=True)
    # Check FK descendants too: redundant project_id can be NULL/inconsistent
    # on legacy records. Never cascade-delete evidence omitted by its adapter.
    for table, keys, rows in _affected_keys(db, project):
        included = {tuple(row.get(key.name) for key in keys) for row in snapshot['records'].get(table.name, [])}
        if any(tuple(row) not in included for row in rows):
            raise HTTPException(409, '存在尚未纳入完整项目备份的关联记录，项目未删除，请联系管理员')
    return snapshot


def prepare(db, project_id, user, *, version, deletion_id):
    path = None
    try:
        project = _locked(db, project_id, user, version, deletion_id)
        before = _snapshot(db, project)
        identifier = str(uuid4())
        # create_project_backup re-reads the exact locked evidence and streams
        # files into AES-GCM; add cycle descriptors using the shared snapshot seam.
        snapshot, path, digest, size = create_project_backup(db, project, identifier, permanent=True)
        if fingerprint(snapshot) != fingerprint(project_backup_snapshot(db, project, include_deletion_snapshots=True)):
            raise OSError('evidence changed while backing up')
        receipt = ProjectPermanentBackup(id=identifier, project_id=project.id, project_name=project.name,
            deletion_id=deletion_id, project_version=version, content_sha256=fingerprint(before),
            backup_name=path.name, backup_sha256=digest, backup_bytes=size,
            prepared_by=user.id, prepared_at=utcnow())
        verified_backup(receipt)  # authenticate the published envelope before committing any receipt
        db.add(receipt)
        log_change(db, None, 'project', project.id, 'purge_backup', user.id,
                   '生成并校验永久删除前的加密项目备份', new_value={'backup_id': identifier, 'sha256': digest, 'deletion_id': deletion_id})
        db.commit()
    except Exception as error:
        db.rollback()
        if path: path.unlink(missing_ok=True)
        if isinstance(error, HTTPException): raise
        raise HTTPException(409, '永久删除前加密备份失败，项目保留在回收站，请核对备份口令与文件完整性') from None
    return receipt_payload(receipt)


def receipt_payload(receipt):
    return {'backup_id': receipt.id, 'project_id': receipt.project_id, 'project_name': receipt.project_name,
            'sha256': receipt.backup_sha256, 'bytes': receipt.backup_bytes, 'encrypted': True,
            'prepared_at': receipt.prepared_at.isoformat(),
            'purged_at': receipt.purged_at.isoformat() if receipt.purged_at else None}


def permanently_delete(db, project_id, user, *, version, deletion_id, backup_id, confirm_name):
    project = _locked(db, project_id, user, version, deletion_id)
    if confirm_name != project.name:
        raise HTTPException(400, '请完整输入项目名称以确认永久删除')
    receipt = db.get(ProjectPermanentBackup, backup_id)
    if (not receipt or receipt.project_id != project.id or receipt.deletion_id != deletion_id
            or receipt.project_version != version or receipt.purged_at):
        raise HTTPException(409, '请为当前删除周期重新生成并下载加密备份')
    try:
        verified_backup(receipt)
        if receipt.content_sha256 != fingerprint(_snapshot(db, project)):
            raise HTTPException(409, '项目记录或文件已变化，请重新生成并下载加密备份')
        receipt.purged_at, receipt.purged_by = utcnow(), user.id
        log_change(db, None, 'project', project.id, 'delete_permanent', user.id,
                   '管理员明确永久删除回收站项目；加密备份继续保留供鉴权下载',
                   new_value={'backup_id': receipt.id, 'deletion_id': deletion_id, 'sha256': receipt.backup_sha256})
        # Delete children in reverse FK dependency order only after all actual
        # scoped rows were proven present in the backup. This handles version
        # records with RESTRICT attachment references on SQLite and PostgreSQL.
        db.flush()
        for table in reversed(Base.metadata.sorted_tables):
            for column in table.columns:
                if any(fk.target_fullname == 'projects.id' for fk in column.foreign_keys):
                    db.execute(delete(table).where(column == project.id))
        db.delete(project)
        db.commit()
    except Exception as error:
        db.rollback()
        if isinstance(error, HTTPException): raise
        raise HTTPException(409, '加密备份校验或永久删除失败，项目未删除') from None
    from app.services.cache import cache_clear
    cache_clear('dashboard:')
    return {'message': '项目已永久删除，加密备份继续保留', **receipt_payload(receipt)}
