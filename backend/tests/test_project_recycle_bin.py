"""Recoverable deletion through the actual HTTP/CAS/visibility seams."""
import hashlib
import io
import json
from datetime import timedelta
from zipfile import ZipFile
from unittest.mock import patch
from contextlib import nullcontext

import pytest
from app.db import SessionLocal
from app.models import Project, User, ProjectDeletionRecord, Attachment, Task, Module, Phase, ScheduleEntry, DailyProgress, PersonalEvent, ProjectSchedulePolicy, TaskDurationOverride, ChangeLog, ProjectGovernanceRequest
from app.time_utils import utcnow


def _project(client, headers, **extra):
    members = extra.pop('members', None)
    r = client.post('/api/projects', headers=headers, json={
        'name': '可恢复项目', 'start_date': '2026-09-01', 'end_date': '2026-12-31', **extra})
    assert r.status_code == 200, r.text
    result = r.json()
    if members is not None:
        changed = client.put(f"/api/projects/{result['id']}", headers=headers, json={'members': members, 'version': result['version']})
        assert changed.status_code == 200, changed.text
        result = changed.json()
    return result


def _policy(client, headers, uid, overrides):
    before = client.get(f'/api/permissions/users/{uid}', headers=headers).json()
    r = client.put(f'/api/permissions/users/{uid}', headers=headers,
                   json={'version': before['version'], 'overrides': overrides})
    assert r.status_code == 200, r.text


def _delete(client, headers, project):
    return client.delete(f"/api/projects/{project['id']}", headers=headers,
                         params={'version': project['version'], 'reason': '隔离测试移入回收站'})


def test_owner_delete_restore_redelete_original_identity_and_independent_backups(client, pm_headers):
    p = _project(client, pm_headers)
    assert p.get('can_delete', True)
    assert client.get(f"/api/projects/{p['id']}", headers=pm_headers).json()['can_delete']
    deleted = _delete(client, pm_headers, p)
    assert deleted.status_code == 200, deleted.text
    first = deleted.json()
    assert first['backup']['available'] and first['backup']['bytes'] > 0
    assert client.get(f"/api/projects/{p['id']}", headers=pm_headers).status_code == 404
    assert all(x['id'] != p['id'] for x in client.get('/api/projects', headers=pm_headers).json())
    rows = client.get('/api/project-recycle-bin/projects', headers=pm_headers).json()
    row = next(x for x in rows if x['id'] == p['id'])
    assert row['can_restore'] and row['deleted_by_name'] and row['status_before_delete'] == 'draft'
    restored = client.post(f"/api/project-recycle-bin/projects/{p['id']}/restore", headers=pm_headers,
        json={'version': row['version'], 'deletion_id': row['deletion_id']})
    assert restored.status_code == 200, restored.text
    original = client.get(f"/api/projects/{p['id']}", headers=pm_headers).json()
    assert original['id'] == p['id'] and original['status'] == 'draft'
    second = _delete(client, pm_headers, original)
    assert second.status_code == 200 and second.json()['deletion_id'] != first['deletion_id']
    with SessionLocal() as db:
        cycles = db.query(ProjectDeletionRecord).filter_by(project_id=p['id']).all()
        assert len(cycles) == 2 and sum(x.restored_at is not None for x in cycles) == 1
        assert db.query(ChangeLog).filter_by(project_id=p['id'], action='delete').count() == 2
        assert db.query(ChangeLog).filter_by(project_id=p['id'], action='restore').count() == 1


def test_explicit_grant_scope_and_deny_override_owner_and_admin(client, admin_headers, pm_headers, worker_headers):
    owned = _project(client, pm_headers, members=['user-worker-001'])
    unrelated = _project(client, admin_headers)
    assert _delete(client, worker_headers, owned).status_code == 403
    _policy(client, admin_headers, 'user-worker-001', {'project.delete': True})
    assert _delete(client, worker_headers, unrelated).status_code == 404
    assert _delete(client, worker_headers, owned).status_code == 200
    assert client.get(f"/api/project-recycle-bin/projects/{owned['id']}", headers=worker_headers).status_code == 200
    _policy(client, admin_headers, 'user-worker-001', {'project.delete': True, 'projects.view_all': True})
    assert _delete(client, worker_headers, unrelated).status_code == 200
    _policy(client, admin_headers, 'user-pm-001', {'project.delete': False})
    other = _project(client, admin_headers, manager_id='user-pm-001')
    assert not client.get(f"/api/projects/{other['id']}", headers=pm_headers).json()['can_delete']
    assert _delete(client, pm_headers, other).status_code == 403
    _policy(client, admin_headers, 'user-admin-001', {'project.delete': False})
    assert _delete(client, admin_headers, other).status_code == 403


@pytest.mark.parametrize('failure', ['write', 'missing', 'traversal', 'symlink'])
def test_backup_failure_is_fail_closed_no_delete_no_audit_or_orphan(client, pm_headers, failure, tmp_path, request):
    from app import config
    from app.services.project_deletion import backup_directory
    p = _project(client, pm_headers)
    previous = set(backup_directory().glob('*.zip*'))
    if failure != 'write':
        stored = '../outside.txt' if failure == 'traversal' else 'missing-test.txt'
        if failure == 'symlink':
            target = tmp_path / 'private.txt'; target.write_text('private')
            stored = 'linked.txt'; (config.UPLOAD_DIR / stored).symlink_to(target)
            request.addfinalizer(lambda: (config.UPLOAD_DIR / stored).unlink(missing_ok=True))
        with SessionLocal() as db:
            db.add(Attachment(project_id=p['id'], entity_type='project', entity_id=p['id'],
                              stored_name=stored, filename='x.txt', file_size=7, uploaded_by='user-pm-001'))
            db.commit()
    with patch('app.services.project_deletion.create_project_backup', side_effect=OSError('disk unavailable')) if failure == 'write' else nullcontext():
        response = _delete(client, pm_headers, p)
    assert response.status_code == 500, response.text
    assert response.json()['detail'] == '删除前项目备份失败，项目未删除'
    with SessionLocal() as db:
        assert db.get(Project, p['id']).deleted_at is None
        assert db.get(Project, p['id']).version == p['version']
        assert db.query(ProjectDeletionRecord).filter_by(project_id=p['id']).count() == 0
        assert db.query(ChangeLog).filter_by(project_id=p['id'], action='delete').count() == 0
    assert set(backup_directory().glob('*.zip*')) == previous


def test_stale_delete_restore_and_cycle_identity_are_atomic(client, pm_headers):
    p = _project(client, pm_headers)
    changed = client.put(f"/api/projects/{p['id']}", headers=pm_headers,
                         json={'version': p['version'], 'name': '新名称'}).json()
    assert _delete(client, pm_headers, p).status_code == 409
    assert _delete(client, pm_headers, changed).status_code == 200
    row = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=pm_headers).json()
    for body in ({'version': row['version'] - 1, 'deletion_id': row['deletion_id']},
                 {'version': row['version'], 'deletion_id': 'not-the-current-cycle'}):
        assert client.post(f"/api/project-recycle-bin/projects/{p['id']}/restore", headers=pm_headers, json=body).status_code == 409
    with SessionLocal() as db:
        assert db.get(Project, p['id']).deleted_at is not None
        assert db.get(ProjectDeletionRecord, row['deletion_id']).restored_at is None
    assert client.post(f"/api/project-recycle-bin/projects/{p['id']}/restore", headers=pm_headers,
        json={'version': row['version'], 'deletion_id': row['deletion_id']}).status_code == 200
    assert client.post(f"/api/project-recycle-bin/projects/{p['id']}/restore", headers=pm_headers,
        json={'version': row['version'], 'deletion_id': row['deletion_id']}).status_code == 409


def test_backup_contains_all_project_evidence_and_bytes_excludes_private_or_other_project(client, pm_headers, tmp_path):
    from app import config
    p = _project(client, pm_headers)
    other = _project(client, pm_headers, name='不应进入备份的项目')
    payload = b'project evidence bytes\x00'
    (config.UPLOAD_DIR / 'evidence-test.bin').write_bytes(payload)
    with SessionLocal() as db:
        phase = Phase(project_id=p['id'], name='实施', sort_order=1); db.add(phase); db.flush()
        module = Module(project_id=p['id'], phase_id=phase.id, name='验证', sort_order=1); db.add(module); db.flush()
        task = Task(project_id=p['id'], module_id=module.id, name='测试任务', target_quantity=1,
                    unit='台', reference_docs=[{'stored_name': 'evidence-test.bin', 'filename': '参考.bin'}])
        db.add(task); db.flush()
        entry = ScheduleEntry(project_id=p['id'], task_id=task.id, work_date=p['start_date'], planned_quantity=1,
                              is_confirmed=True, is_locked=True, assignee_id='user-pm-001')
        # ORM expects dates, unlike API DTOs.
        from datetime import date
        entry.work_date = date.fromisoformat(p['start_date']); db.add(entry); db.flush()
        report = DailyProgress(project_id=p['id'], task_id=task.id, schedule_entry_id=entry.id,
                               user_id='user-pm-001', work_date=entry.work_date, completed_quantity=.25, client_uuid="backup-report-1")
        db.add_all([report, Attachment(project_id=p['id'], entity_type='task', entity_id=task.id,
            stored_name='evidence-test.bin', filename='验收.bin', file_size=len(payload), uploaded_by='user-pm-001'),
            ProjectSchedulePolicy(project_id=p['id'], duration_scale=.5),
            TaskDurationOverride(project_id=p['id'], task_id=task.id, workdays=2, baseline_quantity=1, baseline_unit='台'),
            PersonalEvent(project_id=p['id'], user_id='user-pm-001', work_date=entry.work_date,
                          title='PRIVATE-calendar-not-to-share')])
        db.commit()
    r = _delete(client, pm_headers, p); assert r.status_code == 200, r.text
    binary = client.get(f"/api/project-recycle-bin/projects/{p['id']}/backup",
                       params={'deletion_id': r.json()['deletion_id']}, headers=pm_headers)
    assert binary.status_code == 200
    assert hashlib.sha256(binary.content).hexdigest() == r.json()['backup']['sha256']
    from app.services import backup_crypto as codec
    encrypted = tmp_path / 'project.agvenc'; encrypted.write_bytes(binary.content)
    assert codec.is_encrypted(encrypted)
    with codec.decrypted_file(encrypted, codec.get_passphrase(config.DATA_DIR)) as plain, ZipFile(plain) as bundle:
        assert bundle.testzip() is None
        assert bundle.read('files/evidence-test.bin') == payload
        snapshot = json.loads(bundle.read('project-backup.json'))
        assert snapshot['project']['id'] == p['id']
        assert snapshot['binary_files']['included'] is True
        assert snapshot['records']['task_duration_overrides'][0]['workdays'] == 2
        assert snapshot['records']['project_schedule_policies'][0]['duration_scale'] == .5
        assert snapshot['records']['daily_progress'][0]['completed_quantity'] == .25
        assert snapshot['records']['schedule_entries'][0]['is_locked'] is True
        assert other['id'] not in json.dumps(snapshot)
        assert 'PRIVATE-calendar-not-to-share' not in json.dumps(snapshot)
        assert all(set(actor) == {'id', 'display_name', 'role'} for actor in snapshot['actors'])
        assert 'password_hash' not in json.dumps(snapshot) and 'permission_overrides' not in json.dumps(snapshot)


def test_corrupt_backup_prevents_restore_and_download(client, pm_headers):
    from app.services.project_deletion import _backup_path
    p = _project(client, pm_headers); r = _delete(client, pm_headers, p)
    assert r.status_code == 200, r.text
    row = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=pm_headers).json()
    with SessionLocal() as db:
        _backup_path(db.get(ProjectDeletionRecord, row['deletion_id']).backup_name).write_bytes(b'tampered')
    detail = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=pm_headers).json()
    assert not detail['delete_backup_available'] and not detail['can_restore']
    assert client.post(f"/api/project-recycle-bin/projects/{p['id']}/restore", headers=pm_headers,
        json={'version': row['version'], 'deletion_id': row['deletion_id']}).status_code == 409
    assert client.get(f"/api/project-recycle-bin/projects/{p['id']}/backup", headers=pm_headers,
        params={'deletion_id': row['deletion_id']}).status_code == 409


def test_recoverable_and_legacy_deletions_never_automatically_purged(client, pm_headers):
    from app.services.report_scheduler import purge_soft_deleted_projects
    p = _project(client, pm_headers); old = _project(client, pm_headers)
    assert _delete(client, pm_headers, p).status_code == 200
    with SessionLocal() as db:
        when = utcnow() - timedelta(days=31)
        db.get(Project, p['id']).deleted_at = when
        db.get(Project, old['id']).deleted_at = when
        db.commit()
        result = purge_soft_deleted_projects(db); db.commit()
        assert result['purged'] == 0 and result['disabled']
        assert db.get(Project, p['id']) is not None and db.get(Project, old['id']) is not None


def test_legacy_pending_delete_not_approved_or_automatically_modified(client, pm_headers, admin_headers):
    p = _project(client, pm_headers)
    request = client.post(f"/api/projects/{p['id']}/governance-requests", headers=pm_headers,
                         json={'request_type': 'delete', 'reason': '重复项目清理'})
    assert request.status_code == 400 and '直接删除' in request.json()['detail']
    with SessionLocal() as db:
        legacy = ProjectGovernanceRequest(project_id=p['id'], project_name=p['name'], request_type='delete',
            requested_by='user-pm-001', source_manager_id='user-pm-001', reason='历史删除申请')
        db.add(legacy); db.commit(); rid = legacy.id
    denied = client.post(f'/api/projects/governance/requests/{rid}/review', headers=admin_headers,
                         json={'decision': 'approved'})
    assert denied.status_code == 400
    with SessionLocal() as db:
        assert db.get(ProjectGovernanceRequest, rid).status == 'pending'
        assert db.get(Project, p['id']).deleted_at is None
    # Ordinary project deletion doesn't secretly complete an old request.
    assert _delete(client, pm_headers, p).status_code == 200
    with SessionLocal() as db:
        assert db.get(ProjectGovernanceRequest, rid).status == 'pending'


def test_restore_recovers_missing_file_but_never_overwrites_changed_file(client, pm_headers):
    from app import config
    p = _project(client, pm_headers)
    uploaded = client.post(f"/api/projects/{p['id']}/documents/files", headers=pm_headers,
        files={'file': ('evidence.txt', b'original evidence', 'text/plain')})
    assert uploaded.status_code == 200, uploaded.text
    with SessionLocal() as db:
        file = config.UPLOAD_DIR / db.get(Attachment, uploaded.json()['file']['id']).stored_name
    deleted = _delete(client, pm_headers, p); assert deleted.status_code == 200
    row = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=pm_headers).json()
    file.write_bytes(b'changed externally')
    path = f"/api/project-recycle-bin/projects/{p['id']}/restore"
    body = {'version': row['version'], 'deletion_id': row['deletion_id']}
    assert client.post(path, headers=pm_headers, json=body).status_code == 409
    assert file.read_bytes() == b'changed externally'
    file.unlink()
    restored = client.post(path, headers=pm_headers, json=body)
    assert restored.status_code == 200, restored.text
    assert file.read_bytes() == b'original evidence'
    downloaded = client.get(f"/api/files/{uploaded.json()['file']['id']}/download", headers=pm_headers)
    assert downloaded.status_code == 200 and downloaded.content == b'original evidence'


@pytest.mark.parametrize('operation', ['delete', 'restore'])
def test_actor_disabled_while_waiting_for_project_lock_cannot_write(client, pm_headers, monkeypatch, operation):
    import app.services.project_deletion as deletion
    p = _project(client, pm_headers)
    if operation == 'restore':
        assert _delete(client, pm_headers, p).status_code == 200
        row = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=pm_headers).json()
    original = deletion.lock_record
    def disable_after_lock(db, project, **kwargs):
        original(db, project, **kwargs)
        actor = db.get(User, 'user-pm-001')
        actor.is_active = False
        db.flush()
    monkeypatch.setattr(deletion, 'lock_record', disable_after_lock)
    response = (_delete(client, pm_headers, p) if operation == 'delete' else
        client.post(f"/api/project-recycle-bin/projects/{p['id']}/restore", headers=pm_headers,
                    json={'version': row['version'], 'deletion_id': row['deletion_id']}))
    assert response.status_code == 401, response.text
    with SessionLocal() as db:
        assert (db.get(Project, p['id']).deleted_at is None) == (operation == 'delete')
        assert db.query(ChangeLog).filter_by(project_id=p['id'], action='restore').count() == 0


def test_system_backup_and_staged_restore_keep_project_recovery_files(client, pm_headers, tmp_path, backup_passphrase):
    import shutil
    import tarfile
    from pathlib import Path
    from app import config
    from app.services.system_backup import create_backup, validate_archive
    from app.services.restore_bootstrap import apply_pending_restore
    p = _project(client, pm_headers)
    deleted = _delete(client, pm_headers, p); assert deleted.status_code == 200
    name = deleted.json()['deletion_id'] + '.zip.agvenc'
    expected = (config.DATA_DIR / 'project-deletion-backups' / name).read_bytes()
    archive = create_backup('project-recovery-test')
    assert validate_archive(archive)['type'] == 'agvpm-system-backup'
    from app.services import backup_crypto as codec
    with codec.decrypted_file(archive, backup_passphrase) as plaintext:
        raw = plaintext.read_bytes()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as bundle:
        assert bundle.extractfile('project-deletion-backups/' + name).read() == expected
        assert not any(x.name.startswith('backups/') for x in bundle)
    # Stage into an independent installation directory. The current TestClient
    # engine, uploads and credential file are never replaced.
    destination = tmp_path / 'fresh-install'; destination.mkdir()
    (destination / 'restore-pending.tar.gz').write_bytes(raw)
    codec.set_passphrase(destination, backup_passphrase)
    from app.db import _is_sqlite
    if not _is_sqlite:
        # PostgreSQL restores through restore.sh/pg_restore; bootstrap must leave
        # its dump and deletion evidence pending rather than install partial files.
        with pytest.raises(ValueError, match='待恢复备份不完整'):
            apply_pending_restore(destination)
        assert (destination / 'restore-pending.tar.gz').exists()
        assert not (destination / 'agvpm.db').exists()
        return
    assert apply_pending_restore(destination)
    recovered = destination / 'project-deletion-backups' / name
    assert recovered.read_bytes() == expected
    assert recovered.stat().st_mode & 0o777 == 0o600
    import sqlite3
    with sqlite3.connect(destination / 'agvpm.db') as db:
        row = db.execute('SELECT backup_sha256 FROM project_deletion_records WHERE project_id=?', (p['id'],)).fetchone()
        assert row[0] == hashlib.sha256(recovered.read_bytes()).hexdigest()


def test_system_restore_rejects_nested_recycle_files_and_symlinks():
    import tarfile
    from app.services.backup_safety import safe_members
    for name, type_ in [('project-deletion-backups/../outside.zip', tarfile.REGTYPE),
                        ('project-deletion-backups/subdir/evidence.zip', tarfile.REGTYPE),
                        ('project-deletion-backups/evidence.zip', tarfile.SYMTYPE)]:
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode='w:gz') as bundle:
            item = tarfile.TarInfo(name); item.type = type_; item.linkname = '/private/path'
            bundle.addfile(item)
        raw.seek(0)
        with tarfile.open(fileobj=raw, mode='r:gz') as bundle:
            with pytest.raises(ValueError):
                safe_members(bundle)


def test_backup_filename_collision_never_removes_existing_backup(client, pm_headers):
    from app.services.project_deletion import create_project_backup, _backup_path
    p = _project(client, pm_headers)
    existing = _backup_path('existing-cycle.zip.agvenc')
    existing.write_bytes(b'previous immutable backup')
    with SessionLocal() as db:
        with pytest.raises(FileExistsError):
            create_project_backup(db, db.get(Project, p['id']), 'existing-cycle')
    assert existing.read_bytes() == b'previous immutable backup'


def test_formal_delete_requires_explicit_version(client, pm_headers):
    p = _project(client, pm_headers)
    r = client.delete(f"/api/projects/{p['id']}", headers=pm_headers)
    assert r.status_code == 400 and '版本号' in r.json()['detail']
    assert client.get(f"/api/projects/{p['id']}", headers=pm_headers).status_code == 200



@pytest.mark.parametrize('status', ['archived', 'legacy_unknown'])
def test_deleted_terminal_or_historical_project_restores_original_status(client, pm_headers, status):
    p = _project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, p['id']).status = status; db.commit()
    r = _delete(client, pm_headers, p); assert r.status_code == 200, r.text
    row = client.get(f"/api/project-recycle-bin/projects/{p['id']}", headers=pm_headers).json()
    assert row['status_before_delete'] == status
    restored = client.post(f"/api/project-recycle-bin/projects/{p['id']}/restore", headers=pm_headers,
        json={'version': row['version'], 'deletion_id': row['deletion_id']})
    assert restored.status_code == 200
    assert client.get(f"/api/projects/{p['id']}", headers=pm_headers).json()['status'] == status


def test_backup_is_cleaned_if_database_cas_fails_after_archive_creation(client, pm_headers, monkeypatch):
    from sqlalchemy import update
    import app.services.project_deletion as deletion
    p = _project(client, pm_headers)
    prior = set(deletion.backup_directory().glob('*.zip*'))
    original = deletion.create_project_backup
    def change_version_after_backup(db, project, deletion_id):
        result = original(db, project, deletion_id)
        db.execute(update(Project).where(Project.id == project.id).values(version=Project.version + 1).execution_options(synchronize_session=False))
        return result
    monkeypatch.setattr(deletion, 'create_project_backup', change_version_after_backup)
    assert _delete(client, pm_headers, p).status_code == 409
    assert set(deletion.backup_directory().glob('*.zip*')) == prior
    with SessionLocal() as db:
        assert db.get(Project, p['id']).version == p['version']
        assert db.get(Project, p['id']).deleted_at is None
        assert db.query(ProjectDeletionRecord).filter_by(project_id=p['id']).count() == 0
