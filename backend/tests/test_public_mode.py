"""Public startup fails closed; only configured proxies can establish HTTPS."""
import asyncio
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import config
from app.middleware import HTTPSOnlyMiddleware, TrustedHostsMiddleware
from app.services.public_security import validate_public_settings


VALID = dict(public_mode=True, cookie_secure=True, force_https=True,
             trusted_hosts=["agv.example.com"], forwarded_allow_ips="172.20.1.5")


@pytest.mark.parametrize("key,value", [
    ("cookie_secure", False), ("force_https", False),
    ("trusted_hosts", []), ("trusted_hosts", [""]),
    ("trusted_hosts", ["agv.example.com", "*"]),
    ("trusted_hosts", ["agv.example.com", " "]),
    ("trusted_hosts", ["*.com"]), ("trusted_hosts", ["0.0.0.0/0"]),
    ("trusted_hosts", ["agv.example.com:443"]),
    ("trusted_hosts", ["https://agv.example.com"]),
    ("forwarded_allow_ips", ""), ("forwarded_allow_ips", " "),
    ("forwarded_allow_ips", "*"), ("forwarded_allow_ips", "127.0.0.1,*"),
    ("forwarded_allow_ips", "127.0.0.1,"),
    ("forwarded_allow_ips", "localhost"), ("forwarded_allow_ips", "0.0.0.0"),
    ("forwarded_allow_ips", "0.0.0.0/0"), ("forwarded_allow_ips", "::/0"),
    ("forwarded_allow_ips", "127.0.0.1 --workers 20"),
])
def test_public_configuration_rejects_unsafe_values(key, value):
    with pytest.raises(RuntimeError, match="PUBLIC_MODE=1") as error:
        validate_public_settings(**{**VALID, key: value})
    assert key.upper() in str(error.value)


@pytest.mark.parametrize("proxies", ["127.0.0.1", "172.20.1.0/24", "2001:db8::/64", "::1,172.20.1.5",
                                     "172.16.0.0/12", "192.168.0.0/16", "2001:db8::/48"])
def test_complete_public_configuration_accepts_explicit_proxy_addresses(proxies):
    validate_public_settings(**{**VALID, "forwarded_allow_ips": proxies,
                                "trusted_hosts": ["agv.example.com", "*.team.example.com", "::1"]})


def test_internal_mode_keeps_existing_http_defaults():
    validate_public_settings(public_mode=False, cookie_secure=False, force_https=False,
                             trusted_hosts=["*"], forwarded_allow_ips="")


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.multica.yml"])
def test_public_security_environment_reaches_each_deployment(filename):
    compose = Path(__file__).resolve().parents[2] / "docker" / filename
    service = yaml.safe_load(compose.read_text())["services"]["agv-pm"]
    environment = dict(value.split("=", 1) for value in service["environment"])
    for key, default in (("PUBLIC_MODE", "0"), ("FORCE_HTTPS", "0"), ("COOKIE_SECURE", "0"),
                         ("FORWARDED_ALLOW_IPS", "")):
        assert environment[key] == "${" + key + ":-" + default + "}"


def test_public_startup_rejects_before_initializing_database(monkeypatch):
    from app import main
    initialize = Mock()
    monkeypatch.setattr(main, "init_db", initialize)
    monkeypatch.setattr(config, "PUBLIC_MODE", True)
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    monkeypatch.setattr(config, "FORCE_HTTPS", False)
    monkeypatch.setattr(config, "TRUSTED_HOSTS", ["*"])
    monkeypatch.setattr(config, "FORWARDED_ALLOW_IPS", "")
    with pytest.raises(RuntimeError, match="PUBLIC_MODE=1") as error:
        with TestClient(main.app):
            pass
    for key in ("COOKIE_SECURE", "FORCE_HTTPS", "TRUSTED_HOSTS", "FORWARDED_ALLOW_IPS"):
        assert key in str(error.value)
    initialize.assert_not_called()


def test_complete_public_startup_serves_hsts_and_secure_login_cookies(client, monkeypatch):
    import time
    from app import main
    from app.services import cookies
    from app.services import two_factor as mfa
    monkeypatch.setattr(config, "PUBLIC_MODE", True)
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    monkeypatch.setattr(config, "FORCE_HTTPS", True)
    monkeypatch.setattr(config, "TRUSTED_HOSTS", ["agv.example.com"])
    monkeypatch.setattr(config, "FORWARDED_ALLOW_IPS", "127.0.0.1")
    monkeypatch.setattr(cookies, "COOKIE_SECURE", True)
    with TestClient(main.app, base_url="https://agv.example.com") as secure_client:
        challenge = secure_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert challenge.status_code == 200
        assert challenge.json()['setup_required'] and 'access_token' not in challenge.json()
        assert secure_client.get('/api/auth/me').status_code == 401
        credential = {'challenge': challenge.json()['challenge']}
        setup = secure_client.post('/api/auth/2fa/enroll/start', json=credential)
        assert setup.status_code == 200
        response = secure_client.post('/api/auth/2fa/enroll/confirm', json={
            **credential, 'otp': mfa.totp(setup.json()['secret'], int(time.time()) // 30)})
        logout = secure_client.post("/api/auth/logout", headers={"X-CSRF-Token": secure_client.cookies[config.COOKIE_CSRF_NAME]})
    assert response.status_code == 200, response.text
    assert "max-age=" in response.headers["strict-transport-security"]
    session_cookies = response.headers.get_list("set-cookie")
    assert len(session_cookies) == 4
    assert all("; Secure" in value for value in session_cookies)
    assert logout.status_code == 200
    assert all("; Secure" in value for value in logout.headers.get_list("set-cookie"))


def _request(*, peer="203.0.113.10", path="/", headers=None, method="GET"):
    async def endpoint(request):
        return JSONResponse({"scheme": request.url.scheme, "client": request.client.host})
    app = Starlette(routes=[Route("/", endpoint, methods=["GET", "POST"]), Route("/health", endpoint)])
    app = TrustedHostsMiddleware(HTTPSOnlyMiddleware(app), ["agv.example.com", "127.0.0.1"])
    app = ProxyHeadersMiddleware(app, trusted_hosts="172.20.1.5")

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(peer, 32100)),
                                    base_url="http://agv.example.com", follow_redirects=False) as session:
            return await session.request(method, path, headers=headers)
    return asyncio.run(run())


def test_only_trusted_proxy_can_supply_https_and_client_ip():
    forwarded = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "198.51.100.7"}
    trusted = _request(peer="172.20.1.5", headers=forwarded)
    assert trusted.status_code == 200
    assert trusted.json() == {"scheme": "https", "client": "198.51.100.7"}
    untrusted = _request(headers=forwarded, method="POST")
    assert untrusted.status_code == 307
    assert untrusted.headers["location"] == "https://agv.example.com/"


@pytest.mark.parametrize("forwarded", [None, {"X-Forwarded-Proto": "http"}, {"X-Forwarded-Proto": "wss"}])
def test_proxy_without_valid_https_cannot_reach_business_routes(forwarded):
    assert _request(peer="172.20.1.5", headers=forwarded).status_code == 307


@pytest.mark.parametrize("host", ["evil.example.com", "agv.example.com:443@evil.example.com", "agv.example.com:80/path",
                                 "agv.example.com:" + "9" * 5000, "agv.example.com:²"])
def test_host_rejection_precedes_https_redirect(host):
    response = _request(headers={"Host": host.encode("latin1")})
    assert response.status_code == 400
    assert "location" not in response.headers


def test_only_credential_free_loopback_health_probe_can_use_internal_http():
    probe = _request(peer="127.0.0.1", path="/health", headers={"Host": "127.0.0.1:8000"})
    assert probe.status_code == 200
    assert _request(peer="127.0.0.1").status_code == 307
    assert _request(path="/health").status_code == 307
    authenticated = _request(peer="127.0.0.1", path="/health",
                             headers={"Host": "127.0.0.1:8000", "Authorization": "Bearer test"})
    assert authenticated.status_code == 307
