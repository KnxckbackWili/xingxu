"""Revocation races, signed-purpose separation and public first-boot acceptance."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import subprocess
import sys
import time
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from app import config
from app.db import SessionLocal
from app.models import User, AiApiToken, MfaRecoveryCode
from app.services import two_factor as mfa


@pytest.fixture
def enabled(client, monkeypatch):
    monkeypatch.setattr(config, 'PUBLIC_MODE', False)
    secret = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'
    with SessionLocal() as db:
        user = db.query(User).filter_by(username='pm').one()
        user.mfa_enabled = True; user.mfa_secret_encrypted = mfa.seal(user.id, secret)
        user.mfa_last_step = -1; user.token_version = 5
        codes = mfa.new_codes(db, user)
        uid = user.id
        db.commit()
    return uid, secret, codes


@pytest.mark.parametrize('operation', [mfa.disable, mfa.regenerate])
def test_management_rechecks_authorized_token_version_under_lock(enabled, operation):
    uid, secret, codes = enabled
    with SessionLocal() as db:
        with pytest.raises(mfa.MfaError, match='账号已变化'):
            operation(db, uid, mfa.totp(secret, int(time.time()) // 30), expected_version=4)
        db.rollback()
        user = db.get(User, uid)
        assert user.mfa_enabled and user.token_version == 5 and user.mfa_last_step == -1
        assert db.query(MfaRecoveryCode).filter_by(user_id=uid, used_at=None).count() == 10


def test_atomic_recovery_hash_consumption_with_independent_transactions(enabled):
    uid, _, codes = enabled
    def consume(_):
        with SessionLocal() as db:
            try:
                user = db.get(User, uid)
                mfa.use_recovery(db, user, codes[0]); db.commit(); return True
            except mfa.MfaError:
                db.rollback(); return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == [False, True]


def test_other_admin_cannot_mint_factor_bound_credentials_and_legacy_credentials_fail(enabled, client, monkeypatch):
    uid, secret, codes = enabled
    admin = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'}).json()
    response = client.post('/api/ai/internal/tokens', headers={'Authorization': 'Bearer ' + admin['access_token']}, json={'name': 'not-self', 'user_id': uid})
    assert response.status_code == 403
    raw = 'agv_ai_isolated_legacy_factor_test'
    with SessionLocal() as db:
        db.add(AiApiToken(id=str(uuid4()), user_id=uid, name='legacy no factor proof', token_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=[]))
        db.commit()
    from app.services.agent_auth import authenticate_agent
    with pytest.raises(HTTPException): authenticate_agent('Bearer ' + raw)


def test_cipher_tamper_never_exposes_or_accepts_wrong_seed():
    uid = str(uuid4())
    ciphertext = mfa.seal(uid, 'test-only-totp-key')
    raw = bytearray(base64.urlsafe_b64decode(ciphertext)); raw[-1] ^= 1
    with pytest.raises(mfa.MfaError): mfa.unseal(uid, base64.urlsafe_b64encode(raw).decode())
    with pytest.raises(mfa.MfaError): mfa.unseal(uid, 'broken-ciphertext')


def test_public_first_boot_allows_safe_enrollment_without_business_session(tmp_path):
    data = tmp_path / 'first-boot'
    script = '''
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, base_url='https://testserver') as client:
    assert client.get('/health').status_code == 200
    result = client.post('/api/auth/login', json={'username':'admin','password':'Isolated-first-boot-2026!'})
    assert result.status_code == 200
    body = result.json()
    assert body['setup_required'] and 'access_token' not in body
    assert client.get('/api/auth/me').status_code == 401
print('public enrollment ready')
'''
    env = {**os.environ, 'DATA_DIR': str(data), 'DATABASE_URL': 'sqlite:///' + str(data / 'agvpm.db'),
           'PUBLIC_MODE': '1', 'COOKIE_SECURE': '1', 'FORCE_HTTPS': '1', 'TRUSTED_HOSTS': 'testserver',
           'FORWARDED_ALLOW_IPS': '127.0.0.1', 'SCHEDULER_ENABLED': '0', 'SEED_DEMO_USERS': '0',
           'INITIAL_ADMIN_PASSWORD': 'Isolated-first-boot-2026!', 'PYTHONPATH': str(config.BASE_DIR)}
    result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert 'public enrollment ready' in result.stdout
    reset = subprocess.run([sys.executable, str(config.BASE_DIR / 'scripts/reset_two_factor.py'), '--username', 'admin', '--confirm-username', 'admin'], env=env, capture_output=True, text=True, timeout=20)
    assert reset.returncode == 0, reset.stderr
    import sqlite3
    with sqlite3.connect(data / 'agvpm.db') as database:
        assert database.execute("SELECT token_version,mfa_enabled FROM users WHERE username='admin'").fetchone() == (1, False)
        assert database.execute("SELECT count(*) FROM change_logs WHERE action='mfa_host_reset'").fetchone()[0] == 1
        assert database.execute('SELECT count(*) FROM mfa_challenges').fetchone()[0] == 0


def test_host_recovery_cli_rejects_pending_and_import_has_no_bootstrap_side_effect(tmp_path):
    data = tmp_path / 'host-recovery'; data.mkdir()
    pending = data / 'restore-pending.tar.gz'; pending.write_bytes(b'preserved pending request')
    tool = config.BASE_DIR / 'scripts/reset_two_factor.py'
    env = {**os.environ, 'DATA_DIR': str(data), 'DATABASE_URL': 'sqlite:///' + str(data / 'agvpm.db'), 'PYTHONPATH': str(config.BASE_DIR)}
    result = subprocess.run([sys.executable, str(tool), '--username', 'isolated', '--confirm-username', 'isolated'], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and '存在待恢复请求' in result.stderr
    assert pending.read_bytes() == b'preserved pending request' and not (data / 'agvpm.db').exists()
    script = "import runpy,sys;runpy.run_path(" + repr(str(tool)) + ");assert not getattr(sys,'_xingxu_host_auth_recovery',False);assert 'app.config' not in sys.modules"
    imported = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True)
    assert imported.returncode == 0, imported.stderr
    assert pending.read_bytes() == b'preserved pending request'
