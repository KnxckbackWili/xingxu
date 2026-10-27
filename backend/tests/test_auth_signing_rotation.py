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


def test_rotation_invalidates_external_sessions_but_keeps_share_capability(client, pm_headers, monkeypatch):
    project = client.post('/api/projects', headers=pm_headers, json={'name':'signing scope',
        'start_date':'2026-10-01','end_date':'2026-12-31','module_ids':[]})
    assert project.status_code == 200
    share = client.post('/api/projects/'+project.json()['id']+'/external-shares', headers=pm_headers,
        json={'expires_at':(utcnow()+timedelta(days=1)).isoformat()+'Z'})
    assert share.status_code == 200
    body = {'token':share.json()['token']}
    old = client.post('/api/external/bootstrap', json=body)
    assert old.status_code == 200
    rotate(monkeypatch)
    assert client.get('/api/external/view', headers={'Authorization':'Bearer '+old.json()['session_token']}).status_code == 401
    new = client.post('/api/external/bootstrap', json=body)
    assert new.status_code == 200
    assert client.get('/api/external/view', headers={'Authorization':'Bearer '+new.json()['session_token']}).status_code == 200
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(new.json()['session_token'], config.SECRET_KEY, algorithms=[config.ALGORITHM], audience='external_view')
