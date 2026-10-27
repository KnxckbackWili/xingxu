"""Challenge credentials authenticate before request-field validation."""
import json
import time

import jwt

from app import config
from app.services import two_factor as mfa


CHALLENGE_ROUTES = (
    '/api/auth/2fa/verify', '/api/auth/2fa/enroll/start',
    '/api/auth/2fa/enroll/confirm', '/api/auth/2fa/recover/start', '/api/auth/2fa/cancel',
)


def test_challenge_routes_reject_missing_or_forged_auth_before_body_validation(client):
    requests = [
        {}, {'json': {}}, {'json': []},
        {'json': {'challenge': 'forged', 'otp': {'invalid': 'type'}}},
        {'json': {'challenge': 123}},
        {'content': '{broken', 'headers': {'Content-Type': 'application/json'}},
        {'content': 'missing credentials', 'headers': {'Content-Type': 'text/plain'}},
        {'content': '{"challenge":"forged"}', 'headers': {'Content-Type': 'application/octet-stream'}},
    ]
    for path in CHALLENGE_ROUTES:
        for arguments in requests:
            result = client.post(path, **arguments)
            assert result.status_code == 401, (path, arguments, result.status_code)


def test_valid_enrollment_challenge_keeps_field_validation_and_is_not_consumed(client, monkeypatch):
    monkeypatch.setattr(config, 'PUBLIC_MODE', True)
    step = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'}).json()
    assert 'access_token' not in step
    credential = {'challenge': step['challenge']}
    payload = jwt.decode(step['challenge'], config.SECRET_KEY, algorithms=[config.ALGORITHM], audience='xingxu-mfa')
    expired = jwt.encode({**payload, 'exp': int(time.time()) - 60}, config.SECRET_KEY, algorithm=config.ALGORITHM)
    for path in CHALLENGE_ROUTES:
        assert client.post(path, json={'challenge': expired, 'otp': {}}).status_code == 401
    # A valid enrollment credential is still the wrong purpose for login/recovery.
    for path in ('/api/auth/2fa/verify', '/api/auth/2fa/recover/start'):
        assert client.post(path, json={**credential, 'otp': {}}).status_code == 401
    for path in ('/api/auth/2fa/enroll/start', '/api/auth/2fa/cancel'):
        assert client.post(path, json={**credential, 'extra': 'not allowed'}).status_code == 422
    assert client.post('/api/auth/2fa/enroll/start', content=json.dumps(credential),
                       headers={'Content-Type': 'text/plain'}).status_code == 422
    start = client.post('/api/auth/2fa/enroll/start', json=credential)
    assert start.status_code == 200
    # Invalid fields neither consume the challenge nor count as failed factors.
    for _ in range(9):
        assert client.post('/api/auth/2fa/enroll/confirm', json={**credential, 'otp': {}}).status_code == 422
    assert client.get('/api/auth/me').status_code == 401
    confirmed = client.post('/api/auth/2fa/enroll/confirm', json={
        **credential, 'otp': mfa.totp(start.json()['secret'], int(time.time()) // 30)})
    assert confirmed.status_code == 200
    assert confirmed.json()['access_token']
    assert client.post('/api/auth/2fa/enroll/start', json=credential).status_code == 401
