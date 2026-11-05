"""T14 schema adoption and encrypted full-snapshot recovery of auth secrets."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import config
from app.db import Base, SessionLocal, engine
from app.models import User, MfaRecoveryCode
from app.services import backup_crypto as codec, two_factor as mfa


@pytest.mark.parametrize('external_key', [False, True])
def test_encrypted_full_backup_restores_totp_seed_and_one_use_code_state(client, tmp_path, monkeypatch, external_key):
    from app.db import _is_sqlite
    data = tmp_path / 'source'
    data.mkdir(mode=0o700)
    if external_key:
        monkeypatch.setenv('SECRET_KEY', 'isolated-external-application-secret-t14')
        monkeypatch.setattr(config, 'SECRET_KEY', 'isolated-external-application-secret-t14')
        (data / 'secret.key').write_text('old-stale-file-key')
    else:
        (data / 'secret.key').write_text(config.SECRET_KEY)
    secret = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'
    with SessionLocal() as db:
        user = db.query(User).filter_by(username='admin').one()
        uid = user.id
        user.mfa_enabled = True; user.mfa_secret_encrypted = mfa.seal(uid, secret); user.mfa_last_step = 123456
        codes = mfa.new_codes(db, user)
        db.flush()
        mfa.use_recovery(db, user, codes[0])
        db.commit()
    if _is_sqlite:
        import sqlite3
        with sqlite3.connect(engine.url.database) as source, sqlite3.connect(data / 'agvpm.db') as destination:
            source.backup(destination)
        database_url = 'sqlite'
    else:
        database_url = config.DATABASE_URL
    # The snapshot references seeded template originals; a full backup refuses to omit them.
    import shutil
    shutil.copytree(config.UPLOAD_DIR, data / 'uploads')
    archive = tmp_path / 'full.agvenc'
    password = 'isolated-t14-backup-password'
    codec.create_archive(data, archive, database_url, password)
    restored = tmp_path / 'restored'
    restored.mkdir(mode=0o700)
    with codec.decrypted_file(archive, password) as plain:
        with tarfile.open(plain) as bundle:
            bundle.extractall(restored, filter='data')
    assert (restored / 'secret.key').read_text() == config.SECRET_KEY
    pg_name = None
    isolated = None
    if _is_sqlite:
        # Exercise the actual config-independent snapshot installation protocol.
        install = tmp_path / 'installed'; install.mkdir(mode=0o700)
        codec._module._install_snapshot(install, restored)
        isolated = create_engine('sqlite:///' + str(install / 'agvpm.db'))
        restored_secret = (install / 'secret.key').read_text()
    else:
        url = make_url(config.DATABASE_URL)
        import re
        assert re.search(r'(?:^|_)(?:ci|test|tests|pytest|gate|gates)(?:_|$)', url.database or '', re.I), 'restore target must be an isolated CI/test database'
        pg_name = 'agvm_t14_restore_' + uuid4().hex
        administrative = engine.execution_options(isolation_level='AUTOCOMMIT')
        with administrative.connect() as connection: connection.execute(text(f'CREATE DATABASE "{pg_name}"'))
        target_url = url.set(database=pg_name)
        env = {**os.environ, 'PGPASSWORD': target_url.password or ''}
        result = subprocess.run(['pg_restore', '--no-owner', '--no-privileges', '-h', target_url.host or '127.0.0.1', '-p', str(target_url.port or 5432), '-U', target_url.username, '-d', pg_name, str(restored / 'agvpm.dump')], capture_output=True, env=env)
        assert result.returncode == 0, 'isolated PG restore failed'
        isolated = create_engine(target_url)
        restored_secret = (restored / 'secret.key').read_text()
    try:
        monkeypatch.setattr(config, 'SECRET_KEY', restored_secret)
        with Session(isolated) as db:
            user = db.get(User, uid)
            assert user.mfa_enabled and user.mfa_last_step == 123456
            assert mfa.unseal(uid, user.mfa_secret_encrypted) == secret
            rows = db.query(MfaRecoveryCode).filter_by(user_id=uid).all()
            assert len(rows) == 10
            assert next(row for row in rows if row.code_hash == mfa.code_hash(uid, codes[0])).used_at is not None
            mfa.use_recovery(db, user, codes[1]); db.commit()
            assert db.query(MfaRecoveryCode).filter_by(user_id=uid, used_at=None).count() == 8
    finally:
        if isolated: isolated.dispose()
        if pg_name:
            with engine.execution_options(isolation_level='AUTOCOMMIT').connect() as connection:
                connection.execute(text(f'DROP DATABASE "{pg_name}"'))
