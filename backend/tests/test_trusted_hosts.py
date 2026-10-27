"""HYPE-24: Host 白名单收口导致合法访问被 400 拒绝的回归测试。

故障链路（已复现）：
  部署侧把 `TRUSTED_HOSTS` 收口为静态精确 IP 白名单后，Starlette
  `TrustedHostMiddleware` 只做精确/子域后缀匹配，无法表达"整个局域网网段"，
  于是以下任一合法访问都会被 400 `Invalid host header` 拒绝：
    - 经 NPM/nginx 反代以公网域名访问（Host = 域名）
    - DHCP 重新分配 LAN IP（Host = 未逐条列出的新 IP）
    - 新增网卡/VPN 接口（Host = 白名单外本机其他接口 IP）

修复：`app/middleware.py` 的 `TrustedHostsMiddleware` 在保留 Starlette
精确 + `*.domain` 语义基础上支持 IP 网段（CIDR）条目；未知 Host 仍返回 400，
Host 校验不放开。

本测试直接对该中间件做隔离回归：
  1. 精确主机匹配与 Starlette 语义一致
  2. `*.domain` 子域后缀通配
  3. CIDR 网段命中/未命中
  4. 带端口 Host 剥离
  5. IPv6 字面量带端口
  6. 未知 Host 仍 400（不放开）
  7. `"*"` 显式放行任意 Host
  8. 复现真实部署配置：白名单从精确 IP 改为 `192.168.1.0/24` 后，局域网
     任意 IP 可访问，而外部域名仍被拒绝
"""

import asyncio

import httpx

from app.middleware import TrustedHostsMiddleware


def _wrapped(allowed_hosts):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def index(request):
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/", index)])
    return TrustedHostsMiddleware(inner, allowed_hosts)


def _client(allowed_hosts):
    transport = httpx.ASGITransport(app=_wrapped(allowed_hosts))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0)


def _statuses(allowed_hosts, hosts):
    async def run():
        async with _client(allowed_hosts) as c:
            return [ (await c.get("/", headers={"Host": h})).status_code for h in hosts ]
    return asyncio.run(run())


# ---- 1. 精确主机匹配（与 Starlette 语义一致） ----
def test_exact_host_match():
    hosts = ["127.0.0.1", "localhost", "HUAWEI-Harmony-mini.local"]
    assert _statuses(hosts, hosts) == [200] * 3
    # 未列出的主机被拒
    assert _statuses(hosts, ["192.168.1.42", "agv.example.com"]) == [400, 400]


# ---- 2. *.domain 子域后缀通配 ----
def test_wildcard_subdomain_match():
    # 精确条目只匹配自身；子域需显式 *.domain（与 Starlette 1.x 语义一致）
    assert _statuses(["example.com"], ["example.com", "agv.example.com"]) == [200, 400]
    assert _statuses(["*.example.com"], ["agv.example.com", "deep.agv.example.com"]) == [200, 200]
    assert _statuses(["*.example.com"], ["example.com", "example.com.evil.com"]) == [400, 400]


# ---- 3. CIDR 网段命中/未命中 ----
def test_cidr_subnet_match():
    assert _statuses(["192.168.1.0/24"], ["192.168.1.42", "192.168.1.136"]) == [200, 200]
    assert _statuses(["192.168.1.0/24"], ["192.168.2.5", "10.0.0.7"]) == [400, 400]


# ---- 4. 带端口 Host 剥离 ----
def test_host_port_stripped():
    assert _statuses(["192.168.1.42", "agv.example.com"], ["192.168.1.42:8002", "agv.example.com:443"]) == [200, 200]


# ---- 5. IPv6 字面量带端口 ----
def test_ipv6_literal_with_port():
    assert _statuses(["::1"], ["[::1]:8002"]) == [200]


# ---- 6. 未知 Host 仍 400（不放开校验） ----
def test_unknown_host_rejected():
    assert _statuses(["127.0.0.1", "192.168.1.0/24"], ["agv.example.com", "10.1.2.3"]) == [400, 400]


# ---- 7. "*" 显式放行任意 Host ----
def test_allow_any():
    assert _statuses(["*"], ["anything.example.com", "10.0.0.9"]) == [200, 200]


# ---- 8. 复现真实部署配置：精确 IP 改为 LAN 网段后局域网全通、外部域名仍拒绝 ----
def test_real_deploy_whitelist_regression():
    # 修复前：精确 IP 白名单，DHCP 换 IP/新接口即 400（HYPE-24 现场）
    narrow = ["127.0.0.1", "localhost", "192.168.1.136", "192.168.1.42"]
    assert _statuses(narrow, ["192.168.1.100", "192.168.139.3"]) == [400, 400]
    # 修复后：LAN 网段条目，局域网任意 IP 可访问，外部域名仍拒绝
    wide = ["127.0.0.1", "localhost", "HUAWEI-Harmony-mini.local", "192.168.1.0/24"]
    assert _statuses(wide, ["192.168.1.100", "192.168.1.42", "localhost"]) == [200, 200, 200]
    assert _statuses(wide, ["agv.example.com", "10.0.0.7"]) == [400, 400]
