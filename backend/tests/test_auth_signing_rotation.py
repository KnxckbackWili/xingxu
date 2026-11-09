"""Signing rotation revokes credentials while preserving encrypted application data."""
from datetime import timedelta
import jwt
import pytest
from app import config, deps
from app.services import channel_crypto, two_factor
from app.time_utils import utcnow


def rotate(monkeypatch):
    key = 'isolated-session-signing-rotation-key-2026'
    monkeypatch.setattr(config, 'AUTH_SIGNING_KEY', key)
    monkeypatch.setattr(deps, 'AUTH_SIGNING_KEY', key)
    return key


def test_rotation_rejects_old_access_and_refresh_preserves_encrypted_data(client, monkeypatch):
    old = client.post('/api/auth/login', json={'username':'admin','password':'admin123'}).json()
    encrypted = channel_crypto.encrypt_text('isolated saved channel credential')
    totp = two_factor.seal('isolated-user', 'JBSWY3DPEHPK3PXP')
    key = rotate(monkeypatch)
    assert client.get('/api/auth/me', headers={'Authorization':'Bearer '+old['access_token']}).status_code == 401
    assert client.post('/api/auth/refresh', json={'refresh_token':old['refresh_token']}).status_code == 401
    new = client.post('/api/auth/login', json={'username':'admin','password':'admin123'})
    assert new.status_code == 200
    assert jwt.decode(new.json()['access_token'], key, algorithms=[config.ALGORITHM])['type'] == 'access'
    assert client.post('/api/auth/refresh', json={'refresh_token':new.json()['refresh_token']}).status_code == 200
    assert channel_crypto.decrypt_text(encrypted) == 'isolated saved channel credential'
    assert two_factor.unseal('isolated-user', totp) == 'JBSWY3DPEHPK3PXP'


def test_mfa_challenge_uses_rotated_signing_key_and_rejects_old_key(client, monkeypatch):
    key = rotate(monkeypatch)
    monkeypatch.setattr(config, 'PUBLIC_MODE', True)
    response = client.post('/api/auth/login', json={'username':'admin','password':'admin123'})
    assert response.status_code == 200 and response.json()['two_factor_required']
    token = response.json()['challenge']
    payload = jwt.decode(token, key, algorithms=[config.ALGORITHM], audience='xingxu-mfa')
    forged = jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM)
    assert client.post('/api/auth/2fa/enroll/start', json={'challenge':forged}).status_code == 401
    assert client.post('/api/auth/2fa/enroll/start', json={'challenge':token}).status_code == 200

