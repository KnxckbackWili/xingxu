"""#85: no automatic purge and no permanent deletion without verified ciphertext."""
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import config
from app.db import SessionLocal
from app.models import Project, ProjectDeletionRecord, ProjectPermanentBackup, Attachment, ChangeLog
from app.services import backup_crypto as codec
from app.services import project_permanent_deletion as permanent
from app.services.project_deletion import _backup_path, backup_directory, backup_zip
from .test_project_recycle_bin import _project, _delete


def recycled(client, owner):
    project = _project(client, owner)
    result = _delete(client, owner, project)
    assert result.status_code == 200, result.text
    row = client.get(f"/api/project-recycle-bin/projects/{project['id']}", headers=owner).json()
    return project, row


def prepare(client, admin, row):
    return client.post(f"/api/project-recycle-bin/projects/{row['id']}/permanent-backup", headers=admin,
                       json={'version': row['version'], 'deletion_id': row['deletion_id']})


def purge(client, admin, row, receipt, **extra):
    return client.request('DELETE', f"/api/project-recycle-bin/projects/{row['id']}/permanent", headers=admin,
        json={'version': row['version'], 'deletion_id': row['deletion_id'], 'backup_id': receipt['backup_id'], 'confirm_name': row['name'], **extra})


def test_no_password_backup_failure_keeps_project_and_current_cycle(client, admin_headers, pm_headers, monkeypatch, tmp_path):
    _, row = recycled(client, pm_headers)
    # Keep real test files readable, but make the backup password lookup fail.
    monkeypatch.setattr(permanent, 'create_project_backup', lambda *args, **kwargs: (_ for _ in ()).throw(codec.BackupError('missing private password')))
    assert prepare(client, admin_headers, row).status_code == 409
    with SessionLocal() as db:
        assert db.get(Project, row['id']).deleted_at is not None
        assert db.get(ProjectDeletionRecord, row['deletion_id']).restored_at is None
        assert db.query(ProjectPermanentBackup).count() == 0


@pytest.mark.parametrize('change', ['file', 'record', 'history_snapshot', 'ciphertext', 'name', 'cycle', 'version'])
def test_prepared_receipt_is_bound_to_all_evidence_and_explicit_confirmation(client, admin_headers, pm_headers, change):
    p = _project(client, pm_headers)
    uploaded = client.post(f"/api/projects/{p['id']}/documents/files", headers=pm_headers, files={'file': ('evidence.txt', b'original', 'text/plain')}).json()['file']
    assert _delete(client, pm_headers, p).status_code == 200
    row = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=admin_headers).json()
    response = prepare(client, admin_headers, row); assert response.status_code == 200, response.text
    receipt = response.json(); extra = {}
    with SessionLocal() as db:
        if change == 'file': (config.UPLOAD_DIR / db.get(Attachment, uploaded['id']).stored_name).write_bytes(b'changed!')
        elif change == 'record': db.get(Attachment, uploaded['id']).filename = 'changed-name.txt'; db.commit()
        elif change == 'history_snapshot': db.get(ProjectDeletionRecord, row['deletion_id']).snapshot = {'changed': 'historical deletion evidence'}; db.commit()
        elif change == 'ciphertext':
            path = _backup_path(db.get(ProjectPermanentBackup, receipt['backup_id']).backup_name)
            raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
        elif change == 'name': extra = {'confirm_name': 'wrong project'}
        elif change == 'cycle': extra = {'deletion_id': str(uuid4())}
        elif change == 'version': extra = {'version': row['version'] - 1}
    result = purge(client, admin_headers, row, receipt, **extra)
    assert result.status_code in (400, 409), result.text
    with SessionLocal() as db:
        assert db.get(Project, p['id']) and db.get(Attachment, uploaded['id'])
        assert db.get(ProjectPermanentBackup, receipt['backup_id']).purged_at is None
        assert not db.query(ChangeLog).filter_by(entity_id=p['id'], action='delete_permanent').first()


def test_non_admin_and_explicit_denial_cannot_prepare_or_purge(client, admin_headers, pm_headers, worker_headers):
    _, row = recycled(client, pm_headers)
    assert prepare(client, pm_headers, row).status_code == 403
    assert prepare(client, worker_headers, row).status_code == 403
    receipt = prepare(client, admin_headers, row).json()
    assert purge(client, pm_headers, row, receipt).status_code == 403
    with SessionLocal() as db:
        user = db.get(__import__('app.models', fromlist=['User']).User, 'user-admin-001')
        user.permission_overrides = {'system.projects.purge': False}; db.commit()
    assert prepare(client, admin_headers, row).status_code == 403
    assert purge(client, admin_headers, row, receipt).status_code == 403
    assert client.get('/api/project-recycle-bin/backups/' + receipt['backup_id'], headers=admin_headers).status_code == 403


def test_audit_failure_rolls_back_receipt_and_purge(client, admin_headers, pm_headers, monkeypatch):
    _, row = recycled(client, pm_headers)
    existing = set(backup_directory().iterdir())
    def broken(*args, **kwargs): raise RuntimeError('controlled audit failure')
    with monkeypatch.context() as patch:
        patch.setattr(permanent, 'log_change', broken)
        assert prepare(client, admin_headers, row).status_code == 409
    assert set(backup_directory().iterdir()) == existing
    receipt = prepare(client, admin_headers, row).json()
    with monkeypatch.context() as patch:
        patch.setattr(permanent, 'log_change', broken)
        assert purge(client, admin_headers, row, receipt).status_code == 409
    with SessionLocal() as db:
        assert db.get(Project, row['id']) and db.get(ProjectDeletionRecord, row['deletion_id'])
        assert db.get(ProjectPermanentBackup, receipt['backup_id']).purged_at is None


def test_legacy_plaintext_download_is_encrypted_without_modifying_original(client, pm_headers, tmp_path):
    _, row = recycled(client, pm_headers)
    with SessionLocal() as db:
        record = db.get(ProjectDeletionRecord, row['deletion_id'])
        source = _backup_path(record.backup_name)
        legacy = _backup_path(str(uuid4()) + '.zip')
        with codec.decrypted_file(source, codec.get_passphrase(config.DATA_DIR)) as plain: legacy.write_bytes(plain.read_bytes())
        original = legacy.read_bytes()
        record.backup_name = legacy.name; record.backup_sha256 = hashlib.sha256(original).hexdigest(); record.backup_bytes = len(original); db.commit()
    response = client.get(f"/api/project-recycle-bin/projects/{row['id']}/backup", headers=pm_headers, params={'deletion_id': row['deletion_id']})
    assert response.status_code == 200 and not response.content.startswith(b'PK')
    target = tmp_path / 'download.agvenc'; target.write_bytes(response.content)
    with codec.decrypted_file(target, codec.get_passphrase(config.DATA_DIR)) as plain: assert plain.read_bytes() == original
    assert legacy.read_bytes() == original and not list(backup_directory().glob('.project-download-*'))


def test_two_concurrent_permanent_deletes_have_one_winner(client, admin_headers, pm_headers):
    _, row = recycled(client, pm_headers)
    receipt = prepare(client, admin_headers, row).json()
    def attempt(_):
        from app.models import User
        with SessionLocal() as db:
            try:
                permanent.permanently_delete(db, row['id'], db.get(User, 'user-admin-001'), version=row['version'], deletion_id=row['deletion_id'], backup_id=receipt['backup_id'], confirm_name=row['name'])
                return True
            except HTTPException:
                db.rollback(); return False
    with ThreadPoolExecutor(max_workers=2) as pool: assert sorted(pool.map(attempt, range(2))) == [False, True]


def test_late_fk_insert_cannot_commit_unbacked_evidence_during_final_purge(client, admin_headers, pm_headers, monkeypatch):
    import threading
    from sqlalchemy.exc import IntegrityError, OperationalError
    _, row = recycled(client, pm_headers)
    receipt = prepare(client, admin_headers, row).json()
    locked, started = threading.Event(), threading.Event()
    original = permanent._snapshot
    def snapshot_under_lock(db, project):
        snapshot = original(db, project)
        locked.set(); assert started.wait(5)
        return snapshot
    monkeypatch.setattr(permanent, '_snapshot', snapshot_under_lock)
    def late_insert():
        assert locked.wait(10)
        with SessionLocal() as db:
            started.set()
            db.add(Attachment(project_id=row['id'], entity_type='project', entity_id=row['id'], filename='late evidence', stored_name='late-evidence.bin'))
            try:
                db.commit(); return 'committed-unbacked-evidence'
            except (IntegrityError, OperationalError):
                db.rollback(); return 'rejected'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(late_insert)
        result = purge(client, admin_headers, row, receipt)
        assert result.status_code == 200, result.text
        assert future.result(timeout=10) == 'rejected'


def test_inconsistent_legacy_descendant_not_in_snapshot_blocks_purge(client, admin_headers, pm_headers):
    from app.models import Phase, Module, Task
    p = _project(client, pm_headers)
    with SessionLocal() as db:
        phase = Phase(project_id=p['id'], name='own phase'); db.add(phase); db.flush()
        module = Module(project_id=p['id'], phase_id=phase.id, name='own module'); db.add(module); db.flush()
        # It would cascade via Module, but the explicit project adapter does not
        # claim a template task with no project ownership. Preserve it for repair.
        db.add(Task(project_id=None, module_id=module.id, name='unknown legacy scope'))
        db.commit()
    assert _delete(client, pm_headers, p).status_code == 200
    row = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=admin_headers).json()
    result = prepare(client, admin_headers, row)
    assert result.status_code == 409 and '完整项目备份' in result.text
    with SessionLocal() as db:
        assert db.get(Project, p['id']) and db.query(Task).filter_by(name='unknown legacy scope').count() == 1
