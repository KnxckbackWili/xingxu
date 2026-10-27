"""T14: public enrollment cannot grant business auth; atomic one-use factors."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import time
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import config
from app.db import SessionLocal
from app.models import User, MfaChallenge, MfaRecoveryCode, ChangeLog, AiApiToken
from app.services import two_factor as mfa
from app.time_utils import utcnow


@pytest.fixture
def clock(monkeypatch):
    now = [int(time.time())]
    monkeypatch.setattr(mfa, 'time', SimpleNamespace(time=lambda: now[0]))
    return now


def login(client, username='admin', password='admin123'):
    result = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert result.status_code == 200, result.text
    return result.json()


def headers(session):
    return {'Authorization': 'Bearer ' + session['access_token']}


def enroll(client, clock, *, public=True, username='admin', password='admin123'):
    config.PUBLIC_MODE = public
    step = login(client, username, password)
    if not public:
        result = client.post('/api/auth/2fa/setup', json={'password': password}, headers=headers(step))
        assert result.status_code == 200, result.text
        step = result.json()
    setup = client.post('/api/auth/2fa/enroll/start', json={'challenge': step['challenge']})
    assert setup.status_code == 200, setup.text
    secret = setup.json()['secret']
    confirmed = client.post('/api/auth/2fa/enroll/confirm', json={'challenge': step['challenge'], 'otp': mfa.totp(secret, clock[0] // 30)})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json(), secret


@pytest.fixture(autouse=True)
def restore_public_mode(monkeypatch):
    monkeypatch.setattr(config, 'PUBLIC_MODE', False)


# RFC6238 Appendix B, all six published times and all three hash algorithms.
@pytest.mark.parametrize('timestamp,sha1,sha256,sha512', [
    (59, '94287082', '46119246', '90693936'),
    (1111111109, '07081804', '68084774', '25091201'),
    (1111111111, '14050471', '67062674', '99943326'),
    (1234567890, '89005924', '91819424', '93441116'),
    (2000000000, '69279037', '90698825', '38618901'),
    (20000000000, '65353130', '77737706', '47863826'),
])
def test_rfc6238_vectors(timestamp, sha1, sha256, sha512):
    for algorithm, length, expected in [('sha1', 20, sha1), ('sha256', 32, sha256), ('sha512', 64, sha512)]:
        key = (b'1234567890' * 7)[:length]
        secret = base64.b32encode(key).decode().rstrip('=')
        assert mfa.totp(secret, timestamp // 30, 8, algorithm) == expected


@pytest.mark.parametrize('role', ['admin', 'pm'])
def test_public_existing_user_has_only_purpose_limited_enrollment(client, role):
    old = login(client, role, 'admin123' if role == 'admin' else 'pm123')
    config.PUBLIC_MODE = True
    assert client.get('/health').status_code == 200  # Existing unenrolled accounts do not block startup/health.
    assert client.get('/api/auth/me', headers=headers(old)).status_code == 401
    assert client.post('/api/auth/refresh', json={'refresh_token': old['refresh_token']}).status_code == 401
    step = login(client, role, 'admin123' if role == 'admin' else 'pm123')
    assert step['setup_required'] and 'access_token' not in step and 'user' not in step
    payload = jwt.decode(step['challenge'], config.SECRET_KEY, algorithms=[config.ALGORITHM], audience='xingxu-mfa')
    assert payload['type'] == 'mfa_challenge' and payload['purpose'] == 'enroll'
    assert payload['exp'] - time.time() <= 301
    assert client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + step['challenge']}).status_code == 401
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/refresh', json={'refresh_token': step['challenge']}).status_code == 401
    assert client.post('/api/auth/2fa/verify', json={'challenge': step['challenge'], 'otp': '123456'}).status_code == 401


def test_enrollment_encryption_sessions_recovery_hashes_and_audit(client, clock):
    old = login(client)
    session, secret = enroll(client, clock)
    assert len(set(session['recovery_codes'])) == 10
    assert client.get('/api/auth/me', headers=headers(session)).status_code == 200
    assert client.get('/api/auth/me', headers=headers(old)).status_code == 401
    assert client.post('/api/auth/refresh', json={'refresh_token': session['refresh_token']}).status_code == 200
    with SessionLocal() as db:
        user = db.get(User, session['user']['id'])
        assert user.mfa_enabled and secret not in user.mfa_secret_encrypted
        assert mfa.unseal(user.id, user.mfa_secret_encrypted) == secret
        rows = db.scalars(select(MfaRecoveryCode)).all()
        assert len(rows) == 10 and all(len(row.code_hash) == 64 for row in rows)
        assert {row.code_hash for row in rows} == {mfa.code_hash(user.id, code) for code in session['recovery_codes']}
        challenge = db.scalars(select(MfaChallenge)).one()
        assert challenge.used_at and challenge.pending_secret_encrypted is None
        audit = db.scalars(select(ChangeLog).where(ChangeLog.action == 'mfa_enable')).one()
        serialized = str(audit.new_value) + audit.detail
        assert secret not in serialized and all(code not in serialized for code in session['recovery_codes'])
        with pytest.raises(mfa.MfaError): mfa.unseal(str(uuid4()), user.mfa_secret_encrypted)
        old_key = config.SECRET_KEY
        try:
            config.SECRET_KEY = 'isolated-wrong-app-secret'
            with pytest.raises(mfa.MfaError): mfa.unseal(user.id, user.mfa_secret_encrypted)
        finally: config.SECRET_KEY = old_key


def test_optional_enable_replay_disable_and_new_recovery_codes(client, clock):
    session, secret = enroll(client, clock, public=False)
    assert client.post('/api/auth/2fa/disable', headers=headers(session), json={'otp': mfa.totp(secret, clock[0] // 30)}).status_code == 401
    clock[0] += 30
    regenerated = client.post('/api/auth/2fa/recovery-codes', headers=headers(session), json={'otp': mfa.totp(secret, clock[0] // 30)})
    assert regenerated.status_code == 200 and regenerated.headers['cache-control'] == 'no-store'
    step = login(client)
    assert not step['setup_required']
    assert client.post('/api/auth/2fa/verify', json={'challenge': step['challenge'], 'recovery_code': session['recovery_codes'][0]}).status_code == 401
    recovered = client.post('/api/auth/2fa/verify', json={'challenge': step['challenge'], 'recovery_code': regenerated.json()['recovery_codes'][0]})
    assert recovered.status_code == 200
    clock[0] += 30
    assert client.post('/api/auth/2fa/disable', headers=headers(recovered.json()), json={'otp': mfa.totp(secret, clock[0] // 30)}).status_code == 200
    assert client.get('/api/auth/me', headers=headers(recovered.json())).status_code == 401
    assert 'access_token' in login(client)
    with SessionLocal() as db:
        user = db.get(User, session['user']['id'])
        assert not user.mfa_enabled and user.mfa_secret_encrypted is None
        assert not db.scalars(select(MfaRecoveryCode)).all()
        assert db.scalars(select(ChangeLog).where(ChangeLog.action == 'mfa_disable')).first()


def test_public_disable_denied_and_single_code_can_rebind_without_session(client, clock):
    session, secret = enroll(client, clock)
    clock[0] += 30
    assert client.post('/api/auth/2fa/disable', headers=headers(session), json={'otp': mfa.totp(secret, clock[0] // 30)}).status_code == 401
    step = login(client)
    client.cookies.clear()
    replaced = client.post('/api/auth/2fa/recover/start', json={'challenge': step['challenge'], 'recovery_code': session['recovery_codes'][0]})
    assert replaced.status_code == 200 and replaced.json()['setup_required'] and 'access_token' not in replaced.json()
    assert client.get('/api/auth/me').status_code == 401
    with SessionLocal() as db:
        user = db.get(User, session['user']['id'])
        assert user.mfa_enabled and mfa.unseal(user.id, user.mfa_secret_encrypted) == secret
    new_setup = client.post('/api/auth/2fa/enroll/start', json={'challenge': replaced.json()['challenge']}).json()
    new_secret = new_setup['secret']
    assert new_secret != secret
    result = client.post('/api/auth/2fa/enroll/confirm', json={'challenge': replaced.json()['challenge'], 'otp': mfa.totp(new_secret, clock[0] // 30)})
    assert result.status_code == 200 and len(result.json()['recovery_codes']) == 10
    assert client.get('/api/auth/me', headers=headers(session)).status_code == 401
    assert client.post('/api/auth/2fa/verify', json={'challenge': step['challenge'], 'recovery_code': session['recovery_codes'][0]}).status_code == 401


def test_failures_survive_password_success_rotating_challenges_and_ip(client, clock, monkeypatch):
    session, secret = enroll(client, clock)
    from app.routers import auth
    rotating_ip = [0]
    monkeypatch.setattr(auth, '_login_key', lambda request, username: 'rotating-ip-' + str(rotating_ip[0]) + ':' + username)
    for index in range(auth._LOGIN_LIMIT):
        rotating_ip[0] = index
        step = login(client)
        response = client.post('/api/auth/2fa/verify', json={'challenge': step['challenge'], 'otp': 'invalid'})
        assert response.status_code == 401
    assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'}).status_code == 429
    # A changed IP does not erase the account-wide bucket.
    key = auth._mfa_account_key(session['user']['id'])
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as error: auth._check_login_limit(key, db)
        assert error.value.status_code == 429


def test_challenges_cancel_expire_version_and_purpose_are_enforced(client, clock):
    config.PUBLIC_MODE = True
    first = login(client)
    second = login(client)
    assert client.post('/api/auth/2fa/enroll/start', json={'challenge': first['challenge']}).status_code == 401
    start = client.post('/api/auth/2fa/enroll/start', json={'challenge': second['challenge']})
    assert start.status_code == 200 and start.headers['cache-control'] == 'no-store'
    assert client.post('/api/auth/2fa/cancel', json={'challenge': second['challenge']}).status_code == 200
    assert client.post('/api/auth/2fa/enroll/start', json={'challenge': second['challenge']}).status_code == 401
    third = login(client)
    with SessionLocal() as db:
        row = db.scalars(select(MfaChallenge)).one(); row.expires_at = utcnow() - timedelta(seconds=1); db.commit()
    assert client.post('/api/auth/2fa/enroll/start', json={'challenge': third['challenge']}).status_code == 401
    fourth = login(client)
    with SessionLocal() as db:
        row = db.scalars(select(MfaChallenge)).one(); db.get(User, row.user_id).token_version += 1; db.commit()
    assert client.post('/api/auth/2fa/enroll/start', json={'challenge': fourth['challenge']}).status_code == 401


@pytest.mark.parametrize('factor', ['otp', 'recovery'])
def test_concurrent_factor_and_challenge_only_one_winner(client, clock, factor):
    session, secret = enroll(client, clock)
    clock[0] += 30
    step = login(client)
    def attempt(_):
        with SessionLocal() as db:
            try:
                mfa.verify_login(db, step['challenge'], otp=mfa.totp(secret, clock[0] // 30) if factor == 'otp' else '', recovery_code=session['recovery_codes'][0] if factor == 'recovery' else '')
                return True
            except mfa.MfaError:
                db.rollback(); return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [False, True]
    # Reissuing a password challenge must not make the consumed factor reusable.
    later = login(client)
    with SessionLocal() as db:
        with pytest.raises(mfa.MfaError):
            mfa.verify_login(db, later['challenge'], otp=mfa.totp(secret, clock[0] // 30) if factor == 'otp' else '', recovery_code=session['recovery_codes'][0] if factor == 'recovery' else '')


def test_audit_failure_rolls_back_recovery_consumption(client, clock, monkeypatch):
    session, secret = enroll(client, clock)
    step = login(client)
    def failed(*args, **kwargs): raise RuntimeError('controlled audit failure')
    with monkeypatch.context() as patch:
        patch.setattr(mfa, 'log_change', failed)
        with SessionLocal() as db:
            with pytest.raises(RuntimeError): mfa.verify_login(db, step['challenge'], recovery_code=session['recovery_codes'][0])
    with SessionLocal() as db:
        row = db.scalars(select(MfaRecoveryCode).where(MfaRecoveryCode.code_hash == mfa.code_hash(session['user']['id'], session['recovery_codes'][0]))).one()
        assert row.used_at is None
        assert db.scalars(select(MfaChallenge)).one().used_at is None
        mfa.verify_login(db, step['challenge'], recovery_code=session['recovery_codes'][0])


def test_role_promotion_old_sessions_and_agents_cannot_bypass(client):
    worker = login(client, 'worker1', 'worker123')
    raw = 'agv_ai_' + 'isolated-t14-token'
    with SessionLocal() as db:
        user = db.get(User, worker['user']['id'])
        db.add(AiApiToken(id=str(uuid4()), user_id=user.id, name='isolated legacy agent', token_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=['projects:read']))
        db.commit()
    from app.services.agent_auth import authenticate_agent, enforce_agent_mfa
    identity = authenticate_agent('Bearer ' + raw)
    assert identity[0] == worker['user']['id']
    config.PUBLIC_MODE = True
    with SessionLocal() as db:
        db.get(User, worker['user']['id']).role = 'pm'; db.commit()
    assert client.get('/api/auth/me', headers=headers(worker)).status_code == 401
    assert client.post('/api/auth/refresh', json={'refresh_token': worker['refresh_token']}).status_code == 401
    with pytest.raises(HTTPException): authenticate_agent('Bearer ' + raw)
    from app.services import ai_mcp
    ai_mcp._set_mcp_identity(*identity)
    try:
        with SessionLocal() as db:
            with pytest.raises(HTTPException): ai_mcp._current_user(db)
    finally: ai_mcp._set_mcp_identity('', [])
    with SessionLocal() as db:
        db.get(User, worker['user']['id']).role = 'worker'; db.commit()
        user = db.get(User, worker['user']['id'])
        with pytest.raises(HTTPException): enforce_agent_mfa(db, user, 'missing-id')


def test_agent_tokens_must_be_self_created_after_mfa_and_revoked_on_changes(client, clock):
    session, secret = enroll(client, clock)
    config.PUBLIC_MODE = False  # still enabled => still required
    created = client.post('/api/ai/internal/tokens', headers=headers(session), json={'name': 'isolated MFA agent', 'user_id': session['user']['id']})
    assert created.status_code == 200, created.text
    agent = {'Authorization': 'Bearer ' + created.json()['token']}
    assert client.get('/api/agent/tools', headers=agent).status_code == 200
    from app.services.agent_auth import authenticate_agent, enforce_agent_mfa
    identity = authenticate_agent(agent['Authorization'])
    with SessionLocal() as db:
        row = db.get(AiApiToken, created.json()['id']); row.expires_at = utcnow() - timedelta(seconds=1); db.commit()
        with pytest.raises(HTTPException): enforce_agent_mfa(db, db.get(User, session['user']['id']), identity[1].token_id)
        row.expires_at = None; db.commit()
    with SessionLocal() as db: mfa.host_reset(db, session['user']['id'])
    assert client.get('/api/auth/me', headers=headers(session)).status_code == 401
    assert client.get('/api/agent/tools', headers=agent).status_code == 401
    config.PUBLIC_MODE = True
    assert login(client)['setup_required']
