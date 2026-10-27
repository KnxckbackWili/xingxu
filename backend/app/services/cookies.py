"""HttpOnly Cookie 认证辅助（P2-安全）。

登录/刷新后把 access/refresh token 放进 HttpOnly Cookie（SameSite=Lax），
浏览器 JS 无法读取 token，降低 XSS 窃取面。附带：
- `agvpm_csrf`：非 HttpOnly 的 CSRF 双提交 cookie（JS 读取后回传 X-CSRF-Token 头）；
- `agvpm_session`：会话标记 cookie（JS 判断是否已登录，不泄露 token 本身）。

Bearer 头认证仍然保留（API 客户端/旧会话兼容），CSRF 中间件只对
「cookie 认证且无 Bearer」的写请求做校验。
"""

import hmac
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import Response

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    COOKIE_ACCESS_NAME,
    COOKIE_CSRF_NAME,
    COOKIE_REFRESH_NAME,
    COOKIE_SECURE,
    COOKIE_SAMESITE,
    COOKIE_SESSION_MARKER,
    REFRESH_TOKEN_EXPIRE_DAYS,
)


def _base_cookie_kwargs(age: int) -> dict:
    return {
        "path": "/",
        "httponly": True,
        "samesite": COOKIE_SAMESITE,
        "secure": COOKIE_SECURE,
        "max_age": age,
    }


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """登录/刷新成功后设置会话 Cookie。"""
    access_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    refresh_age = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    response.set_cookie(COOKIE_ACCESS_NAME, access_token, **_base_cookie_kwargs(access_age))
    # 刷新 token 限定只发给 /api/auth/refresh，缩小泄露面
    response.set_cookie(
        COOKIE_REFRESH_NAME, refresh_token,
        path="/api/auth/refresh", httponly=True, samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE, max_age=refresh_age,
    )
    # CSRF 双提交 cookie：JS 需读取后回传 X-CSRF-Token 头，因此非 HttpOnly
    csrf = _generate_csrf_token()
    response.set_cookie(
        COOKIE_CSRF_NAME, csrf,
        path="/", httponly=False, samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE, max_age=refresh_age,
    )
    # 会话标记（非 HttpOnly）：前端用它判断登录态，不含 token 本体
    response.set_cookie(
        COOKIE_SESSION_MARKER, "1",
        path="/", httponly=False, samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE, max_age=refresh_age,
    )


def clear_auth_cookies(response: Response) -> None:
    """登出：清除全部会话 Cookie。"""
    for name in (COOKIE_ACCESS_NAME, COOKIE_REFRESH_NAME, COOKIE_CSRF_NAME, COOKIE_SESSION_MARKER):
        response.delete_cookie(name, path="/", secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE)
    # refresh cookie 限定 path=/api/auth/refresh，需按同 path 删除
    response.delete_cookie(COOKIE_REFRESH_NAME, path="/api/auth/refresh", secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE)


def get_access_token(request: Request) -> str | None:
    """从 Authorization 头或 HttpOnly Cookie 读取 access token。"""
    return request.cookies.get(COOKIE_ACCESS_NAME)


def is_cookie_auth(request: Request) -> bool:
    """请求是否依赖 Cookie 认证（有 access cookie 且无 Bearer 头）。"""
    auth = request.headers.get("authorization", "")
    if auth.strip().lower().startswith("bearer "):
        return False
    return bool(request.cookies.get(COOKIE_ACCESS_NAME))


def verify_csrf(request: Request) -> None:
    """CSRF 双提交校验：仅对 cookie 认证的写请求生效。

    X-CSRF-Token 头必须与 agvpm_csrf cookie 一致（恒定时间比较）。
    Bearer 认证请求（API 客户端/旧会话）天然免疫 CSRF，跳过。
    """
    if not is_cookie_auth(request):
        return
    header = request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get(COOKIE_CSRF_NAME, "")
    if not header or not cookie or not hmac.compare_digest(header, cookie):
        raise HTTPException(status_code=403, detail="CSRF 校验失败，请刷新页面后重试")


def _generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
