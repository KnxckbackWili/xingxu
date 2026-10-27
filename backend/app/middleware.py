"""Host 校验中间件：精确主机/域名 + IP 网段（CIDR）条目。

替代 Starlette 自带 `TrustedHostMiddleware`。HYPE-24 暴露的故障链路：

  1. 部署侧为收口暴露面，把 `TRUSTED_HOSTS` 配成静态精确 IP 白名单
     （回环 + 本机 hostname + 两个 LAN IP）。
  2. Starlette `TrustedHostMiddleware` 只做精确匹配或 `*.domain` 后缀通配，
     无法表达"整个局域网网段"；未逐条列出的 Host 一律 400 `Invalid host header`。
  3. 任一合法访问主机变化——DHCP 重新分配 LAN IP、新增网卡/VPN 接口、经
     NPM/nginx 反代以公网域名访问——都会让用户看到 `Invalid host header`。

匹配规则（顺序）：

  1. 条目 `"*"` → 放行任意 Host（显式配置，等价于不校验；默认不启用）。
  2. 条目 `*.domain` → 子域后缀通配（与 Starlette 语义一致）。
  3. 普通条目 → 精确匹配（Host 去端口、去尾点、小写后按字符串相等比较）。
  4. 条目 `a.b.c.d/n` 且可解析为 IP 网段 → Host 解析为 IP 且落在网段内即放行。

未命中任何条目仍返回 400 `Invalid host header`——Host 校验不放开。
"""

import ipaddress

from starlette.datastructures import Headers
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.responses import PlainTextResponse


def _local_health_check(scope) -> bool:
    """Only the container's credential-free loopback probe can use HTTP."""
    if (scope["type"] != "http" or scope.get("path") != "/health"
            or scope.get("method") not in ("GET", "HEAD")):
        return False
    headers = Headers(scope=scope)
    if headers.get("cookie") or headers.get("authorization"):
        return False
    peer = scope.get("client")
    try:
        return (peer is not None and ipaddress.ip_address(peer[0]).is_loopback
                and TrustedHostsMiddleware._host(headers.get("host", "")) in ("127.0.0.1", "::1", "localhost"))
    except ValueError:
        return False


class HTTPSOnlyMiddleware:
    """Use the ASGI scheme verified by uvicorn, never raw forwarded headers."""
    def __init__(self, app):
        self.app = app
        self.redirect = HTTPSRedirectMiddleware(app)

    async def __call__(self, scope, receive, send):
        if _local_health_check(scope):
            await self.app(scope, receive, send)
        else:
            if scope["type"] in ("http", "websocket"):
                secure = "https" if scope["type"] == "http" else "wss"
                if scope.get("scheme") != secure:
                    scope = {**scope, "scheme": "http" if scope["type"] == "http" else "ws"}
            await self.redirect(scope, receive, send)


class TrustedHostsMiddleware:
    def __init__(self, app, allowed_hosts):
        self.app = app
        if allowed_hosts is None:
            allowed_hosts = ["*"]
        self.allow_any = "*" in allowed_hosts
        self.allowed_hosts = []
        self.allowed_subnets = []
        for pattern in allowed_hosts:
            p = pattern.strip().lower().rstrip(".")
            if "/" in p:
                try:
                    self.allowed_subnets.append(ipaddress.ip_network(p, strict=False))
                    continue
                except ValueError:
                    pass  # 不是合法网段，退回精确匹配
            self.allowed_hosts.append(p)

    @staticmethod
    def _host(host_header: str) -> str:
        """从 Host 头提取主机名：去端口、去 IPv6 括号、去尾点、小写。"""
        def valid_port(value):
            return (value.isascii() and 1 <= len(value) <= 5 and value.isdecimal()
                    and 0 < int(value) <= 65535)

        host = host_header.strip().lower()
        if any(ord(c) <= 32 or ord(c) == 127 or c in "/\\@?#" for c in host):
            return ""
        if host.startswith("["):
            # [::1]:8002 → ::1
            end = host.find("]")
            if end == -1:
                return ""
            suffix = host[end + 1:]
            if suffix and (not suffix.startswith(":") or not valid_port(suffix[1:])):
                return ""
            host = host[1:end]
            try:
                ipaddress.IPv6Address(host)
            except ValueError:
                return ""
        elif host.count(":") == 1:
            # example.com:8002 / 1.2.3.4:8002 → 去端口
            host, port = host.split(":", 1)
            if not valid_port(port):
                return ""
        elif ":" in host:
            return ""
        return host.rstrip(".")

    def _is_valid(self, host: str) -> bool:
        for pattern in self.allowed_hosts:
            if host == pattern:
                return True
            if pattern.startswith("*") and host.endswith(pattern[1:]):
                return True
        if self.allowed_subnets:
            try:
                addr = ipaddress.ip_address(host)
            except ValueError:
                addr = None
            if addr is not None:
                return any(addr in net for net in self.allowed_subnets)
        return False

    async def __call__(self, scope, receive, send):
        if self.allow_any or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        host = self._host(Headers(scope=scope).get("host", ""))
        if host and self._is_valid(host):
            await self.app(scope, receive, send)
        else:
            response = PlainTextResponse("Invalid host header", status_code=400)
            await response(scope, receive, send)


class StaticAssetCompressionMiddleware:
    """Compress build assets while leaving authenticated APIs and streams untouched."""

    def __init__(self, app):
        from starlette.middleware.gzip import GZipMiddleware
        self.app = app
        self.compressed_app = GZipMiddleware(app, minimum_size=1024, compresslevel=5)

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] == 'http' and path.startswith('/assets/') and path.endswith(('.js', '.css', '.svg', '.json')):
            await self.compressed_app(scope, receive, send)
        else:
            await self.app(scope, receive, send)
