"""Auth dependencies for FastAPI."""

from datetime import timedelta
from app.time_utils import utcnow
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.config import (
    AUTH_SIGNING_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS,
    COOKIE_ACCESS_NAME,
)
from app.db import get_db
from app.models import User

security = HTTPBearer(auto_error=False)

TOKEN_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="未登录或登录已过期",
    headers={"WWW-Authenticate": "Bearer"},
)


def create_token(user: User, refresh: bool = False, *, mfa_verified: bool = False, verified_version: int | None = None) -> str:
    """Create JWT access or refresh token."""
    if refresh:
        expire = utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        token_type = "refresh"  # nosec B105
    else:
        expire = utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        token_type = "access"  # nosec B105
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "type": token_type,
        "tv": (user.token_version or 0) if verified_version is None else verified_version,
        "mfa": mfa_verified,  # 只有完成当前二次验证后才能置为 True
        "exp": expire,
    }
    return jwt.encode(payload, AUTH_SIGNING_KEY, algorithm=ALGORITHM)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: current authenticated user.

    双通道：优先 Bearer 头（API 客户端/旧会话）；无 Bearer 时读取 HttpOnly
    Cookie `agvpm_access`（浏览器会话）。两者都缺失 → 401。
    """
    token = credentials.credentials if credentials is not None else request.cookies.get(COOKIE_ACCESS_NAME)
    if not token:
        raise TOKEN_EXCEPTION
    try:
        payload = jwt.decode(token, AUTH_SIGNING_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise TOKEN_EXCEPTION
        user_id = payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    except jwt.PyJWTError:
        raise TOKEN_EXCEPTION

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise TOKEN_EXCEPTION
    expected_account=request.headers.get('X-AGV-Expected-Account')
    if expected_account and expected_account!=user.id:
        raise HTTPException(status_code=401,detail='登录账号已变化；原视图操作未执行，请重新核验账号')
    # 令牌版本校验：改密/重置密码后旧 token 一律失效
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    from app.services.two_factor import session_allowed
    if not session_allowed(user, payload):
        raise HTTPException(status_code=401, detail="此账号需要完成二次验证，请重新登录")
    # Explicit system denials apply on every authenticated route, including
    # routes whose legacy handler accepts every signed-in role.
    from app.services.system_permissions import permission_for_request, permission_override
    required = permission_for_request(request)
    from app.services.system_permissions import readonly_request_allowed, PERMISSIONS
    if user.role == "readonly" and not readonly_request_allowed(request):
        raise HTTPException(status_code=403, detail="只读预设：此操作未对只读账号开放；请联系管理员调整账号预设")
    for capability in ([required] if isinstance(required, str) else required or []):
        if permission_override(user, capability) is False:
            raise HTTPException(status_code=403, detail=f"系统禁止：{PERMISSIONS[capability]['name']}（{capability}）")
    return user


def require_roles(*roles: str):
    """Dependency factory: require one of the given roles."""
    def checker(request: Request, user: User = Depends(get_current_user)) -> User:
        from app.services.system_permissions import permission_for_request, has_permission
        required = permission_for_request(request)
        capabilities = [required] if isinstance(required, str) else required or []
        if user.role not in roles and not (capabilities and all(
            has_permission(user, capability, default=False) for capability in capabilities
        )):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限执行此操作")
        return user
    return checker


# Convenience role checkers
require_admin = require_roles("admin")
require_pm = require_roles("admin", "pm")
