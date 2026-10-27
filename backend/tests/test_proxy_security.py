"""T024: 代理头信任加固回归测试（FORWARDED_ALLOW_IPS）。

背景：T023 为让 NPM 反代拿到真实客户端 IP 与 https scheme，uvicorn 以
`--proxy-headers --forwarded-allow-ips *` 启动。二审（2026-08-25）指出：
`*` 默认信任任意来源，而 8002 端口又以 `0.0.0.0:8002` 直曝局域网，LAN 客户端
可伪造 `X-Forwarded-For/Proto` 污染登录审计的客户端 IP，并绕过登录暴力破解限流
（`auth.py` 的 `_login_key` 依赖 `request.client.host`）。

T024 方案：`FORWARDED_ALLOW_IPS` 默认不信任任意来源（空 → uvicorn 仅回环
127.0.0.1 可信，见 `docker/supervisord.conf`），显式配置 NPM 可信地址/网段才信任。

本测试用 uvicorn 生产同款 `ProxyHeadersMiddleware`（uvicorn `--proxy-headers`
实际挂载的中间件）包裹真实 app，并通过 ASGITransport 指定直连对端 IP，忠实复现
容器内 uvicorn 行为：

  1. 默认（仅回环可信）：非回环对端伪造 X-Forwarded-For 无效 → 登录失败桶 key
     使用真实对端 IP（审计 IP 不可污染）。
  2. 默认：轮换伪造头无法绕过登录限流 → 第 9 次仍按真实对端触发 429。
  3. 显式可信网段（NPM 前置）：来自可信网段的 X-Forwarded-For 生效 → 登录失败
     桶 key 使用转发头中的真实客户端 IP。
"""

import asyncio

import httpx
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.routers import auth

# FORWARDED_ALLOW_IPS 为空 → supervisord 不传 --forwarded-allow-ips → uvicorn 仅回环可信
DEFAULT_TRUSTED = "127.0.0.1"
# 显式配置示例：NPM 所在可信网段（如 Docker 桥接网段）
NPM_TRUSTED_NET = "172.16.0.0/12"
# 非可信 LAN 直连客户端（伪造头来源）
LAN_PEER = "192.168.1.50"
# 可信代理（NPM 容器）
TRUSTED_PROXY_PEER = "172.16.5.1"
# 伪造的"真实客户端"IP
FAKE_CLIENT = "203.0.113.9"


def _proxy_client(peer_ip: str, trusted: str) -> httpx.AsyncClient:
    """用 uvicorn 生产同款 ProxyHeadersMiddleware 包裹 app，指定直连对端 IP。"""
    from app.main import app
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=trusted)
    transport = httpx.ASGITransport(app=wrapped, client=(peer_ip, 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://agv.test", timeout=30.0)


async def _login(c: httpx.AsyncClient, username: str, password: str, forged: str):
    return await c.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"X-Forwarded-For": forged},
    )


@pytest.fixture()
def proxy_db():
    """Fresh 表 + 种子，并清空登录限流状态（不依赖 TestClient lifespan，直接 init_db）。"""
    from app.db import engine, Base, init_db
    Base.metadata.drop_all(bind=engine)
    from sqlalchemy import text
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS alembic_version'))
    from app.services.rate_limit import reset_rate_limits
    reset_rate_limits()
    auth._login_failures.clear()
    init_db()
    yield
    auth._login_failures.clear()


def _failed_keys() -> list[str]:
    if auth._is_sqlite:
        return list(auth._login_failures.keys())
    from app.db import SessionLocal
    from app.models import LoginFailureBucket
    with SessionLocal() as db:
        return [key for (key,) in db.query(LoginFailureBucket.key).filter(
            LoginFailureBucket.count > 0).distinct().all()]


def test_default_untrusted_forged_header_ignored_for_audit_ip(proxy_db):
    """默认（仅回环可信）：LAN 客户端伪造 X-Forwarded-For 无效，审计 IP 用真实对端。"""
    async def run():
        async with _proxy_client(LAN_PEER, DEFAULT_TRUSTED) as c:
            r = await _login(c, "admin", "wrong", FAKE_CLIENT)
            return r.status_code
    assert asyncio.run(run()) == 401
    keys = _failed_keys()
    assert any(k.startswith(f"{LAN_PEER}:") for k in keys), keys
    assert not any(k.startswith(f"{FAKE_CLIENT}:") for k in keys), keys


def test_default_forged_header_cannot_bypass_login_rate_limit(proxy_db):
    """默认：轮换伪造头无法绕过登录限流，第 9 次仍按真实对端触发 429。"""
    async def run():
        async with _proxy_client(LAN_PEER, DEFAULT_TRUSTED) as c:
            statuses = []
            for i in range(9):
                statuses.append((await _login(c, "admin", "wrong", f"203.0.113.{i}")).status_code)
            return statuses
    statuses = asyncio.run(run())
    assert statuses[:8] == [401] * 8, statuses
    assert statuses[8] == 429, statuses  # 伪造头轮换不生效，仍按真实对端计数


def test_trusted_proxy_header_applied_for_audit_ip(proxy_db):
    """显式可信网段：NPM 代理转发的 X-Forwarded-For 生效，审计 IP 用转发客户端。"""
    async def run():
        async with _proxy_client(TRUSTED_PROXY_PEER, NPM_TRUSTED_NET) as c:
            r = await _login(c, "admin", "wrong", FAKE_CLIENT)
            return r.status_code
    assert asyncio.run(run()) == 401
    keys = _failed_keys()
    assert any(k.startswith(f"{FAKE_CLIENT}:") for k in keys), keys
    assert not any(k.startswith(f"{TRUSTED_PROXY_PEER}:") for k in keys), keys
