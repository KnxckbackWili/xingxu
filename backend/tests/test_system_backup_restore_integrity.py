"""系统备份恢复的验证、并发与失败回滚。"""

import io
import tarfile
import pytest
from app.services import backup_crypto as codec
from pydantic import SecretStr


def _encrypt(raw, directory, password):
    source = directory / "source.tar.gz"
    encrypted = directory / "source.agvenc"
    source.write_bytes(raw)
    encrypted.unlink(missing_ok=True)
    codec.encrypt_file(source, encrypted, password)
    return encrypted.read_bytes()


def _plain(raw, directory, password):
    encrypted = directory / "download.agvenc"
    encrypted.write_bytes(raw)
    with codec.decrypted_file(encrypted, password) as source:
        return source.read_bytes()


def _archive(database):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, content in [("manifest.json", b'{"type":"agvpm-system-backup","database":"sqlite"}'),
                              ("agvpm.db", database)]:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


def test_restore_rejects_truncated_sqlite_and_preserves_pending(client, admin_headers, monkeypatch, tmp_path, backup_passphrase):
    from app.routers import system
    pending = tmp_path / "restore-pending.tar.gz"
    pending.write_bytes(b"previous valid pending restore")
    monkeypatch.setattr(system, "PENDING_RESTORE", pending)
    response = client.post("/api/system/restore?confirm=RESTORE", headers=admin_headers,
                           data={"passphrase": backup_passphrase},
                           files={"file": ("truncated.agvenc", _encrypt(_archive(b"SQLite format 3\x00"), tmp_path, backup_passphrase), "application/octet-stream")})
    assert response.status_code == 400, response.text
    assert pending.read_bytes() == b"previous valid pending restore"


def test_valid_system_backup_passes_restore_validation(client, admin_headers, monkeypatch, tmp_path, backup_passphrase):
    from app.routers import system
    pending = tmp_path / "restore-pending.tar.gz"
    monkeypatch.setattr(system, "PENDING_RESTORE", pending)
    created = client.post("/api/system/backups", headers=admin_headers, json={"label": "round5"})
    assert created.status_code == 200
    archive = client.get(f"/api/system/backups/{created.json()['filename']}", headers=admin_headers)
    staged = client.post("/api/system/restore?confirm=RESTORE", headers=admin_headers,
                         data={"passphrase": backup_passphrase},
                         files={"file": ("valid.agvenc", archive.content, "application/octet-stream")})
    from app.db import _is_sqlite
    if _is_sqlite:
        assert staged.status_code == 200, staged.text
        assert pending.read_bytes() == _plain(archive.content, tmp_path, backup_passphrase)
    else:
        assert staged.status_code == 400, staged.text
        assert 'PostgreSQL 部署不支持网页恢复' in staged.json()['detail']
        assert not pending.exists()


def test_restore_rejects_valid_but_unrelated_database(client, admin_headers, monkeypatch, tmp_path, backup_passphrase):
    import sqlite3
    from app.routers import system
    pending = tmp_path / "restore-pending.tar.gz"
    monkeypatch.setattr(system, "PENDING_RESTORE", pending)
    unrelated = tmp_path / "unrelated.db"
    with sqlite3.connect(unrelated) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
    rejected = client.post("/api/system/restore?confirm=RESTORE", headers=admin_headers,
                           data={"passphrase": backup_passphrase},
                           files={"file": ("unrelated.agvenc", _encrypt(_archive(unrelated.read_bytes()), tmp_path, backup_passphrase), "application/octet-stream")})
    assert rejected.status_code == 400
    from app.db import _is_sqlite
    expected = '核心数据表' if _is_sqlite else 'PostgreSQL 部署不支持网页恢复'
    assert expected in rejected.json()['detail']
    assert not pending.exists()
    # Validate the malformed SQLite backup directly in the PG job too.
    from app.services.system_backup import validate_archive
    path = tmp_path / 'unrelated.tar.gz'
    path.write_bytes(_archive(unrelated.read_bytes()))
    with pytest.raises(ValueError, match='核心数据表'):
        validate_archive(path)


def test_concurrent_restore_uploads_use_independent_staging_files(client, monkeypatch, tmp_path, backup_passphrase):
    import asyncio
    from app.routers import system
    # Exercise SQLite's staging-file implementation without changing the suite DB.
    monkeypatch.setattr(system, 'DATABASE_URL', 'sqlite://')
    pending = tmp_path / "restore-pending.tar.gz"
    monkeypatch.setattr(system, "PENDING_RESTORE", pending)
    monkeypatch.setattr(system, "validate_archive", lambda path: {"label": path.read_bytes().decode(), "database": "sqlite"})
    monkeypatch.setattr(system, "log_change", lambda *args, **kwargs: None)
    class Actor: id = "admin"
    class Database:
        def commit(self): pass
    first = _encrypt(b"first", tmp_path, backup_passphrase)
    second = _encrypt(b"second", tmp_path, backup_passphrase)
    class YieldingUpload:
        filename = "concurrent.agvenc"
        def __init__(self, content):
            self.content = io.BytesIO(content)
        async def read(self, size):
            await asyncio.sleep(0)
            return self.content.read(size)
    async def upload_both():
        return await asyncio.gather(*[
            system.stage_restore(file=YieldingUpload(label), confirm="RESTORE", passphrase=SecretStr(backup_passphrase), actor=Actor(), db=Database())
            for label in (first, second)
        ], return_exceptions=True)
    results = asyncio.run(upload_both())
    assert all(isinstance(result, dict) for result in results)
    assert {result["manifest"]["label"] for result in results} == {"first", "second"}
    assert pending.read_bytes() in (b"first", b"second")


def test_restore_file_swap_failure_rolls_back_database_uploads_and_key(monkeypatch, tmp_path):
    from pathlib import Path
    from app.services.restore_bootstrap import _install_snapshot
    live, staged = tmp_path / "live", tmp_path / "staged"
    live.mkdir(); staged.mkdir()
    for directory, label in [(live, b"old"), (staged, b"new")]:
        (directory / "agvpm.db").write_bytes(label + b" db")
        (directory / "secret.key").write_bytes(label + b" key")
        (directory / "uploads").mkdir()
        (directory / "uploads" / "reference.txt").write_bytes(label + b" attachment")
    (live / "agvpm.db-wal").write_bytes(b"old wal")
    (live / "agvpm.db-shm").write_bytes(b"old shm")
    original_replace = Path.replace
    def fail_upload_swap(path, target):
        if path == staged / "uploads":
            raise OSError("simulated replacement failure")
        return original_replace(path, target)
    monkeypatch.setattr(Path, "replace", fail_upload_swap)
    with pytest.raises(OSError, match="simulated replacement failure"):
        _install_snapshot(live, staged)
    assert (live / "agvpm.db").read_bytes() == b"old db"
    assert (live / "agvpm.db-wal").read_bytes() == b"old wal"
    assert (live / "agvpm.db-shm").read_bytes() == b"old shm"
    assert (live / "secret.key").read_bytes() == b"old key"
    assert (live / "uploads" / "reference.txt").read_bytes() == b"old attachment"


def test_staged_restore_applies_complete_snapshot_and_keeps_pre_restore_backup(client, admin_headers, tmp_path, backup_passphrase):
    import sqlite3
    from app.services.restore_bootstrap import apply_pending_restore
    from app.services.system_backup import validate_archive
    created = client.post("/api/system/backups", headers=admin_headers, json={"label": "apply"})
    exported = client.get(f"/api/system/backups/{created.json()['filename']}", headers=admin_headers)
    exported_plain = _plain(exported.content, tmp_path, backup_passphrase)
    codec.set_passphrase(tmp_path, backup_passphrase)
    from app.db import _is_sqlite
    if not _is_sqlite:
        # A PG dump must never replace SQLite files during bootstrap.
        pending = tmp_path / 'restore-pending.tar.gz'
        pending.write_bytes(exported_plain)
        secret = tmp_path / 'secret.key'
        secret.write_bytes(b'unchanged installation secret')
        with pytest.raises(ValueError, match='待恢复备份不完整'):
            apply_pending_restore(tmp_path)
        assert secret.read_bytes() == b'unchanged installation secret'
        assert pending.read_bytes() == exported_plain
        return
    with tarfile.open(fileobj=io.BytesIO(exported_plain), mode="r:gz") as archive:
        (tmp_path / "agvpm.db").write_bytes(archive.extractfile("agvpm.db").read())
        # The pre-restore installation must be a complete snapshot too. Missing
        # ordinary originals correctly prevent its mandatory encrypted backup.
        from pathlib import PurePosixPath
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if not member.isfile() or not path.parts or path.parts[0] != 'uploads':
                continue
            assert not path.is_absolute() and '..' not in path.parts
            destination = tmp_path.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.extractfile(member).read())
    with sqlite3.connect(tmp_path / "agvpm.db") as db:
        db.execute("UPDATE users SET display_name = 'old installation' WHERE username = 'admin'")
    (tmp_path / "uploads").mkdir(exist_ok=True)
    (tmp_path / "uploads" / "old.txt").write_bytes(b"old attachment")
    (tmp_path / "secret.key").write_bytes(b"old test secret")
    pending = tmp_path / "restore-pending.tar.gz"
    pending.write_bytes(exported_plain)
    assert apply_pending_restore(tmp_path) is True
    assert not pending.exists()
    assert apply_pending_restore(tmp_path) is False
    with sqlite3.connect(tmp_path / "agvpm.db") as db:
        assert db.execute("SELECT display_name FROM users WHERE username = 'admin'").fetchone()[0] != "old installation"
    assert not (tmp_path / "uploads" / "old.txt").exists()
    assert (tmp_path / "secret.key").read_bytes() != b"old test secret"
    preserved = list((tmp_path / "backups").glob("agvpm-pre-restore-*.tar.gz.agvenc"))
    assert len(preserved) == 1
    assert validate_archive(preserved[0])["label"] == "pre-restore"


def test_concurrent_same_second_backups_do_not_overwrite(client, monkeypatch, tmp_path, backup_passphrase):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime
    from app.services import system_backup
    class FixedTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 9, 30, 12, 0, 0)
    monkeypatch.setattr(system_backup, "datetime", FixedTime)
    monkeypatch.setattr(system_backup, "BACKUP_DIR", tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(system_backup.create_backup, ["same-time", "same-time"]))
    assert len(set(paths)) == 2
    assert len(list(tmp_path.glob("agvpm-*.tar.gz.agvenc"))) == 2
    assert all(system_backup.validate_archive(path)["label"] == "same-time" for path in paths)


def test_failed_backup_is_never_published(client, monkeypatch, tmp_path, backup_passphrase):
    from app.services import system_backup
    monkeypatch.setattr(system_backup, "BACKUP_DIR", tmp_path)
    class FailedArchive:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def addfile(self, *args, **kwargs):
            assert not list(tmp_path.glob("agvpm-*.tar.gz.agvenc"))
            raise OSError("simulated archive write failure")
    monkeypatch.setattr(codec._module.tarfile, "open", lambda *args, **kwargs: FailedArchive())
    with pytest.raises(OSError, match="simulated archive write failure"):
        system_backup.create_backup("failed")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("alias", ["./agvpm.db", "uploads//reference.txt", "uploads/./reference.txt"])
def test_restore_rejects_paths_that_alias_validated_archive_members(tmp_path, alias):
    import sqlite3
    from app.services.system_backup import validate_archive
    database = tmp_path / "valid.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE users (id, username, password_hash, role, is_active)")
        db.execute("CREATE TABLE projects (id, name)")
        db.execute("CREATE TABLE tasks (id, project_id, module_id, name)")
    malicious = tmp_path / "alias.tar.gz"
    with tarfile.open(malicious, "w:gz") as archive:
        for name, content in [
            ("manifest.json", b'{"type":"agvpm-system-backup"}'),
            ("agvpm.db", database.read_bytes()),
            ("uploads/reference.txt", b"valid reference"),
            (alias, b"corrupt replacement"),
        ]:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    with pytest.raises(ValueError, match="路径"):
        validate_archive(malicious)


def test_restore_allows_normal_directory_suffix_but_rejects_aliased_duplicates():
    from app.services.backup_safety import safe_members
    def directory_archive(names):
        content = io.BytesIO()
        with tarfile.open(fileobj=content, mode="w:gz") as archive:
            for name in names:
                member = tarfile.TarInfo(name)
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
        content.seek(0)
        return tarfile.open(fileobj=content, mode="r:gz")
    with directory_archive(["uploads/"]) as archive:
        assert len(safe_members(archive)) == 1
    with directory_archive(["uploads", "uploads/"]) as archive:
        with pytest.raises(ValueError, match="重复路径"):
            safe_members(archive)
