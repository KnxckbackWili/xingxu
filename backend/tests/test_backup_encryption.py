"""T12: authenticated, streaming backups and password-aware restore behavior."""
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tarfile

import pytest

from app.services import backup_crypto as codec

PASSWORD = "test-only-backup-password-2026"


def installation(path):
    path.mkdir(mode=0o700)
    with sqlite3.connect(path / "agvpm.db") as db:
        db.executescript("""
            CREATE TABLE users (id TEXT, username TEXT, password_hash TEXT, role TEXT, is_active BOOLEAN);
            CREATE TABLE projects (id TEXT, name TEXT);
            CREATE TABLE tasks (id TEXT, project_id TEXT, module_id TEXT, name TEXT);
            INSERT INTO users VALUES ('u','admin','private-password-hash','admin',1);
            INSERT INTO projects VALUES ('p','retained project');
            INSERT INTO tasks VALUES ('t','p','m','retained task');
        """)
    (path / "secret.key").write_text("persisted-application-key")
    (path / "system-update-config.json").write_text('{"encrypted_token":"retained-ciphertext"}')
    (path / "uploads").mkdir()
    (path / "uploads/photo.bin").write_bytes(b"private-attachment\x00" * 100)
    exports = path / "migration-exports/t03/owners/owner-id"
    exports.mkdir(parents=True)
    (exports / "evidence.agvr").write_bytes(b"owner-separated-encrypted-retirement-evidence")
    codec.set_passphrase(path, PASSWORD)
    return path


def test_archive_is_encrypted_and_preserves_sensitive_contents_without_password_settings(tmp_path):
    data = installation(tmp_path / "data")
    archive = tmp_path / "system.tar.gz.agvenc"
    codec.create_archive(data, archive, "sqlite", PASSWORD)
    assert not tarfile.is_tarfile(archive)
    assert PASSWORD.encode() not in archive.read_bytes()
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert codec.validate_archive(archive, PASSWORD)["database"] == "sqlite"
    with codec.decrypted_file(archive, PASSWORD) as plain:
        assert stat.S_IMODE(plain.stat().st_mode) == 0o600
        assert stat.S_IMODE(plain.parent.stat().st_mode) == 0o700
        with tarfile.open(plain) as bundle:
            assert not any(name.startswith("backup-security") for name in bundle.getnames())
            assert bundle.extractfile("secret.key").read() == b"persisted-application-key"
            assert bundle.extractfile("uploads/photo.bin").read() == (data / "uploads/photo.bin").read_bytes()
            assert bundle.extractfile("migration-exports/t03/owners/owner-id/evidence.agvr").read() == (data / "migration-exports/t03/owners/owner-id/evidence.agvr").read_bytes()
    assert not plain.exists()


@pytest.mark.parametrize("change", ["wrong-password", "tag", "header", "truncate", "ciphertext"])
def test_failed_authentication_never_yields_plaintext_and_cleans_private_staging(tmp_path, change):
    source = tmp_path / "source"
    source.write_bytes(os.urandom(2 * 1024 * 1024))
    encrypted = tmp_path / "backup.agvenc"
    codec.encrypt_file(source, encrypted, PASSWORD)
    raw = bytearray(encrypted.read_bytes())
    password = PASSWORD
    if change == "wrong-password":
        password = "another-test-backup-password"
    elif change == "tag":
        raw[-1] ^= 1
    elif change == "header":
        raw[12] ^= 1
    elif change == "truncate":
        raw = raw[:-10]
    else:
        raw[100] ^= 1
    encrypted.write_bytes(raw)
    with pytest.raises(codec.BackupError):
        with codec.decrypted_file(encrypted, password):
            pytest.fail("Unauthenticated plaintext escaped its private scope")
    assert not list(tmp_path.glob(".backup-decrypt-*"))


def test_streamed_large_payload_roundtrip_and_no_replace_publication(tmp_path):
    source = tmp_path / "large"
    with source.open("wb") as output:
        for _ in range(12):
            output.write(os.urandom(1024 * 1024))
    encrypted = tmp_path / "archive.agvenc"
    codec.encrypt_file(source, encrypted, PASSWORD)
    original = encrypted.read_bytes()
    with pytest.raises(FileExistsError):
        codec.encrypt_file(source, encrypted, PASSWORD)
    assert encrypted.read_bytes() == original
    with codec.decrypted_file(encrypted, PASSWORD) as plain, source.open("rb") as expected, plain.open("rb") as actual:
        while block := expected.read(1024 * 1024):
            assert actual.read(len(block)) == block
        assert actual.read(1) == b""
    assert not list(tmp_path.glob(".backup-encrypted-*"))


def test_password_store_is_private_and_independent_of_restored_application_secret(tmp_path):
    data = installation(tmp_path / "data")
    stored = data / "backup-security/credentials.json"
    assert PASSWORD not in stored.read_text()
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert stat.S_IMODE((data / "backup-security/key").stat().st_mode) == 0o600
    (data / "secret.key").write_text("a-restored-earlier-app-key")
    assert codec.get_passphrase(data) == PASSWORD
    codec.set_passphrase(data, "new-test-backup-password-2026")
    assert codec.get_passphrase(data) == "new-test-backup-password-2026"


def test_new_backup_refuses_missing_password_without_plaintext_fallback(client, monkeypatch, tmp_path):
    from app.services import system_backup
    monkeypatch.setattr(system_backup, "DATA_DIR", tmp_path)
    monkeypatch.delenv("BACKUP_PASSPHRASE_FILE", raising=False)
    with pytest.raises(codec.BackupError, match="尚未设置"):
        system_backup.create_backup()
    assert not list(tmp_path.iterdir())


def test_setting_requires_real_admin_and_audits_no_secret(client, admin_headers, pm_headers, worker_headers):
    body = {"passphrase": PASSWORD}
    for headers in [pm_headers, worker_headers]:
        assert client.put("/api/system/backup-encryption", headers=headers, json=body).status_code == 403
    result = client.put("/api/system/backup-encryption", headers=admin_headers, json=body)
    assert result.status_code == 200 and result.json()["configured"]
    assert PASSWORD not in result.text
    from app.db import SessionLocal
    from app.models import ChangeLog
    with SessionLocal() as db:
        row = db.query(ChangeLog).filter_by(entity_type="system_backup", action="configure").one()
        assert PASSWORD not in str(row.new_value) + row.detail


def test_web_download_always_encrypts_new_and_historical_backup(client, admin_headers, monkeypatch, tmp_path):
    from app.services import system_backup
    from app.routers import system
    from app.config import DATA_DIR
    codec.set_passphrase(DATA_DIR, PASSWORD)
    monkeypatch.setattr(system, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(system_backup, "BACKUP_DIR", tmp_path)
    historical = tmp_path / "agvpm-historical.tar.gz"
    historical.write_bytes(b"historical plaintext bytes are preserved")
    response = client.get("/api/system/backups/" + historical.name, headers=admin_headers)
    assert response.status_code == 200 and not response.content.startswith(b"historical")
    assert historical.read_bytes() == b"historical plaintext bytes are preserved"
    encrypted = tmp_path / "download.agvenc"
    encrypted.write_bytes(response.content)
    with codec.decrypted_file(encrypted, PASSWORD) as plain:
        assert plain.read_bytes() == historical.read_bytes()
    created = client.post("/api/system/backups", headers=admin_headers, json={})
    assert created.status_code == 200 and created.json()["encrypted"]
    response = client.get("/api/system/backups/" + created.json()["filename"], headers=admin_headers)
    encrypted.write_bytes(response.content)
    assert codec.validate_archive(encrypted, PASSWORD)["type"] == "agvpm-system-backup"


def test_restore_rejects_wrong_password_or_tag_without_replacing_pending(client, admin_headers, monkeypatch, tmp_path):
    from app.config import DATA_DIR
    from app.routers import system
    codec.set_passphrase(DATA_DIR, PASSWORD)
    if system.DATABASE_URL.startswith("postgresql"):
        pytest.skip("PostgreSQL restoration is exercised through the host restore tool")
    source = installation(tmp_path / "source")
    backup = tmp_path / "backup.agvenc"
    codec.create_archive(source, backup, "sqlite", PASSWORD)
    pending = tmp_path / "restore-pending.tar.gz"
    pending.write_bytes(b"previous verified pending request")
    monkeypatch.setattr(system, "PENDING_RESTORE", pending)
    for raw, password in [(backup.read_bytes(), "wrong-test-backup-password"), (backup.read_bytes()[:-1] + bytes([backup.read_bytes()[-1] ^ 1]), PASSWORD)]:
        response = client.post("/api/system/restore?confirm=RESTORE", headers=admin_headers,
                               data={"passphrase": password}, files={"file": ("backup.agvenc", raw)})
        assert response.status_code == 400 and "认证失败" in response.json()["detail"]
        assert pending.read_bytes() == b"previous verified pending request"
    response = client.post("/api/system/restore?confirm=RESTORE", headers=admin_headers,
                           data={"passphrase": PASSWORD}, files={"file": ("backup.agvenc", backup.read_bytes())})
    assert response.status_code == 200
    assert tarfile.is_tarfile(pending) and stat.S_IMODE(pending.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".backup-decrypt-*"))


def test_password_audit_failure_restores_the_previous_configuration(client, admin_headers, monkeypatch):
    from app.config import DATA_DIR
    from app.routers import system
    codec.set_passphrase(DATA_DIR, PASSWORD)
    def broken_audit(*args, **kwargs):
        raise RuntimeError("controlled audit failure")
    monkeypatch.setattr(system, "log_change", broken_audit)
    with pytest.raises(RuntimeError, match="controlled audit failure"):
        client.put("/api/system/backup-encryption", headers=admin_headers,
                   json={"passphrase": "different-test-only-backup-password"})
    assert codec.get_passphrase(DATA_DIR) == PASSWORD


def test_backup_configuration_requires_permission_even_for_real_admin(client, admin_headers):
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        actor = db.query(User).filter_by(username="admin").one()
        actor.permission_overrides = {"system.backups.configure": False}
        db.commit()
    assert client.put("/api/system/backup-encryption", headers=admin_headers,
                      json={"passphrase": PASSWORD}).status_code == 403


def test_sqlite_web_restore_refuses_a_postgres_archive_before_changing_pending(client, admin_headers, monkeypatch, tmp_path):
    from app.config import DATA_DIR
    from app.routers import system
    monkeypatch.setattr(system, "DATABASE_URL", "sqlite://")
    codec.set_passphrase(DATA_DIR, PASSWORD)
    raw = tmp_path / "postgres.tar.gz"
    with tarfile.open(raw, "w:gz") as bundle:
        for name, content in [("manifest.json", b'{"type":"agvpm-system-backup","database":"postgres"}'),
                              ("agvpm.dump", b"PGDMParchive-structure-fixture")]:
            member = tarfile.TarInfo(name); member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
    sealed = tmp_path / "postgres.agvenc"; codec.encrypt_file(raw, sealed, PASSWORD)
    pending = tmp_path / "restore-pending.tar.gz"; pending.write_bytes(b"prior valid request")
    monkeypatch.setattr(system, "PENDING_RESTORE", pending)
    response = client.post("/api/system/restore?confirm=RESTORE", headers=admin_headers,
                           data={"passphrase": PASSWORD}, files={"file": ("postgres.agvenc", sealed.read_bytes())})
    assert response.status_code == 400 and "只能恢复 SQLite" in response.json()["detail"]
    assert pending.read_bytes() == b"prior valid request"


def test_same_second_migration_snapshots_keep_earliest_and_historical_plaintext(client, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from app import db as database
    from app import config
    data = installation(tmp_path / "migration")
    historical = data / "backups"; historical.mkdir()
    old = historical / "agvpm-before-migrate-20000101-000000.sql"; old.write_bytes(b"historical preserved")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(database, "_is_sqlite", True)
    snapshot_engine = create_engine("sqlite:///" + str(data / "agvpm.db"), connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", snapshot_engine)
    import time
    monkeypatch.setattr(time, "strftime", lambda *args: "20261027-010101")
    database._backup_before_migrate()
    first = next(historical.glob("*.agvenc")); first_bytes = first.read_bytes()
    with sqlite3.connect(data / "agvpm.db") as db:
        db.execute("UPDATE projects SET name='changed after first snapshot'")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: database._backup_before_migrate(), range(2)))
    snapshots = list(historical.glob("*.agvenc"))
    assert len(snapshots) == 3 and first.read_bytes() == first_bytes
    with codec.decrypted_file(first, PASSWORD) as plain, sqlite3.connect(plain) as db:
        assert db.execute("SELECT name FROM projects").fetchone()[0] == "retained project"
    assert old.read_bytes() == b"historical preserved"
    assert not list(historical.glob(".before-migrate-*"))
    snapshot_engine.dispose()


def test_sqlite_restore_preserves_login_attachments_settings_and_retirement_evidence(tmp_path):
    from app.services.restore_bootstrap import apply_pending_restore
    source = installation(tmp_path / "source")
    destination = installation(tmp_path / "destination")
    (destination / "secret.key").write_text("old installation key")
    (destination / "system-update-config.json").write_text("old settings")
    (destination / "migration-exports/old-evidence").write_text("pre-restore retained only in encrypted snapshot")
    sealed = tmp_path / "backup.agvenc"; codec.create_archive(source, sealed, "sqlite", PASSWORD)
    with codec.decrypted_file(sealed, PASSWORD) as plain:
        (destination / "restore-pending.tar.gz").write_bytes(plain.read_bytes())
    assert apply_pending_restore(destination)
    with sqlite3.connect(destination / "agvpm.db") as db:
        assert db.execute("SELECT username,password_hash FROM users").fetchall() == [("admin", "private-password-hash")]
    for name in ["secret.key", "system-update-config.json", "uploads/photo.bin", "migration-exports/t03/owners/owner-id/evidence.agvr"]:
        assert (destination / name).read_bytes() == (source / name).read_bytes()
    assert codec.get_passphrase(destination) == PASSWORD
    snapshots = list((destination / "backups").glob("*.agvenc")); assert len(snapshots) == 1
    with codec.decrypted_file(snapshots[0], PASSWORD) as plain, tarfile.open(plain) as bundle:
        assert bundle.extractfile("secret.key").read() == b"old installation key"
        assert "migration-exports/old-evidence" in bundle.getnames()
    assert not list(destination.glob(".restore-rollback-*"))


def test_postgres_encrypted_dump_roundtrip_preserves_accounts_and_encrypted_settings(client, backup_passphrase, tmp_path, monkeypatch):
    """Real PG17 tools; restore into a newly created, uniquely named test DB."""
    from app import config
    from app.db import engine, SessionLocal, _is_sqlite
    if _is_sqlite:
        pytest.skip("Real PostgreSQL roundtrip belongs to the PostgreSQL job")
    import subprocess
    from uuid import uuid4
    import psycopg2
    from psycopg2 import sql
    from app.models import NotificationChannelConfig
    from app.services.channel_crypto import encrypt_text, decrypt_text
    from app.services import system_updates
    from app.routers.auth import pwd_context
    url = engine.url
    params = url.translate_connect_args()
    params.update({key: value for key, value in url.query.items() if key in {"host", "port", "sslmode"}})
    params["dbname"] = params.pop("database")
    params["user"] = params.pop("username")
    name = "agvm_t12_restore_test_" + uuid4().hex[:16]
    assert name.startswith("agvm_t12_restore_test_")
    private_attachment = config.DATA_DIR / "uploads" / (name + ".bin")
    private_attachment.write_bytes(b"PG roundtrip private attachment")
    with SessionLocal() as db:
        db.add(NotificationChannelConfig(channel="t12-test", enabled=False,
               webhook_url_encrypted=encrypt_text("test-only-channel-value")))
        db.commit()
    settings = config.DATA_DIR / "system-update-config.json"
    prior_settings = settings.read_bytes() if settings.exists() else None
    settings.write_text(json.dumps({"token_encrypted": system_updates._fernet().encrypt(b"test-only-repository-token").decode()}))
    archive = tmp_path / "postgres.agvenc"
    created = False
    admin = psycopg2.connect(**{**params, "dbname": "postgres"}); admin.autocommit = True
    try:
        codec.create_archive(config.DATA_DIR, archive, config.DATABASE_URL, backup_passphrase)
        corrupted = tmp_path / "corrupted.agvenc"
        corrupted.write_bytes(archive.read_bytes()[:-1] + bytes([archive.read_bytes()[-1] ^ 1]))
        for path, password in [(archive, "wrong-test-only-password"), (corrupted, backup_passphrase)]:
            with pytest.raises(codec.BackupError, match="认证失败"):
                codec.validate_archive(path, password)
        work = tmp_path / "verified"; work.mkdir(mode=0o700)
        with codec.decrypted_file(archive, backup_passphrase) as plaintext, tarfile.open(plaintext) as bundle:
            bundle.extractall(work, members=codec.safe_members(bundle), filter="data")
        assert (work / "uploads" / private_attachment.name).read_bytes() == private_attachment.read_bytes()
        assert not (work / "backup-security").exists()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
            created = True
        env = {**os.environ, "PGPASSWORD": str(params.get("password", ""))}
        result = subprocess.run(["pg_restore", "-h", str(params.get("host", "127.0.0.1")), "-p", str(params.get("port", 5432)),
                                 "-U", params["user"], "-d", name, "--no-owner", "--no-privileges", str(work / "agvpm.dump")],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, "PostgreSQL isolated restore failed"
        restored = psycopg2.connect(**{**params, "dbname": name})
        try:
            with restored.cursor() as cursor:
                cursor.execute("SELECT username,password_hash FROM users WHERE username='admin'")
                username, password_hash = cursor.fetchone()
                assert username == "admin" and pwd_context.verify("admin123", password_hash)
                cursor.execute("SELECT webhook_url_encrypted FROM notification_channel_configs WHERE channel='t12-test'")
                encrypted_channel = cursor.fetchone()[0]
            monkeypatch.setattr(config, "SECRET_KEY", (work / "secret.key").read_text().strip())
            assert decrypt_text(encrypted_channel) == "test-only-channel-value"
            recovered_settings = json.loads((work / "system-update-config.json").read_text())
            assert system_updates._fernet().decrypt(recovered_settings["token_encrypted"].encode()) == b"test-only-repository-token"
        finally:
            restored.close()
    finally:
        if created:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()
        private_attachment.unlink(missing_ok=True)
        if prior_settings is None:
            settings.unlink(missing_ok=True)
        else:
            settings.write_bytes(prior_settings)


def test_a_password_reader_cannot_observe_an_uncommitted_password(tmp_path):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    data = installation(tmp_path / "locked")
    writer_entered, reader_started, finish_writer = Event(), Event(), Event()
    def change_then_fail():
        try:
            with codec.passphrase_update(data, "uncommitted-test-only-password"):
                writer_entered.set()
                assert finish_writer.wait(5)
                raise RuntimeError("audit transaction failed")
        except RuntimeError:
            return
    def read_password():
        reader_started.set()
        return codec.get_passphrase(data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(change_then_fail)
        assert writer_entered.wait(5)
        reader = pool.submit(read_password)
        assert reader_started.wait(5)
        try:
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.1)
        finally:
            finish_writer.set()
        writer.result(timeout=5)
        assert reader.result(timeout=5) == PASSWORD


def test_postgres_migration_snapshots_from_same_second_processes_never_overwrite(client, backup_passphrase, tmp_path):
    from app import config
    from app.db import _is_sqlite
    if _is_sqlite:
        pytest.skip("Real pg_dump subprocess collision test belongs to the PostgreSQL job")
    import subprocess
    import sys
    data = installation(tmp_path / "pg-migration")
    script = "from app import db; import time; time.strftime=lambda *args:'20261027-010101'; db._backup_before_migrate()"
    env = {**os.environ, "DATA_DIR": str(data), "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
           "DATABASE_URL": config.DATABASE_URL, "SCHEDULER_ENABLED": "0"}
    first = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True)
    assert first.returncode == 0 and "迁移前 PG 备份成功" in first.stderr
    original = next((data / "backups").glob("*.agvenc")); original_bytes = original.read_bytes()
    processes = [subprocess.Popen([sys.executable, "-c", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    for process in processes:
        _, error = process.communicate(timeout=60)
        assert process.returncode == 0 and "迁移前 PG 备份成功" in error
    assert len(list((data / "backups").glob("*.agvenc"))) == 3
    assert original.read_bytes() == original_bytes
    with codec.decrypted_file(original, PASSWORD) as plaintext:
        assert plaintext.read_bytes().startswith(b"--")


def test_cli_raw_snapshot_decryption_requires_authentication_and_never_overwrites(tmp_path):
    import subprocess
    import sys
    runtime = Path(__file__).resolve().parents[2] / "docker/scripts/backup_runtime.py"
    raw = tmp_path / "snapshot.sql"; raw.write_bytes(b"-- retained pre-migration SQL")
    sealed = tmp_path / "snapshot.sql.agvenc"; codec.encrypt_file(raw, sealed, PASSWORD)
    password_file = tmp_path / "password"; password_file.write_text("wrong-test-only-password"); password_file.chmod(0o600)
    output = tmp_path / "recovered.sql"
    command = [sys.executable, str(runtime), "decrypt-file", "--data-dir", str(tmp_path), "--input", str(sealed),
               "--output", str(output), "--passphrase-file", str(password_file)]
    rejected = subprocess.run(command, capture_output=True, text=True)
    assert rejected.returncode and not output.exists() and "认证失败" in rejected.stderr
    password_file.write_text(PASSWORD)
    accepted = subprocess.run(command, capture_output=True, text=True)
    assert accepted.returncode == 0 and output.read_bytes() == raw.read_bytes()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert output.read_bytes() == raw.read_bytes()


def test_corrupted_password_settings_fail_closed_and_allow_reconfiguration(tmp_path):
    data = installation(tmp_path / "settings")
    (data / "backup-security/credentials.json").write_text("[]")
    assert codec.passphrase_status(data)["configured"] is False
    with pytest.raises(codec.BackupError, match="重新设置"):
        codec.get_passphrase(data)
    codec.set_passphrase(data, PASSWORD)
    assert codec.get_passphrase(data) == PASSWORD
