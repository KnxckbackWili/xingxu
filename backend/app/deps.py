"""Who is calling: the signed-in account, from a Bearer header or the HttpOnly session cookie."""
from datetime import timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import (ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, AUTH_SIGNING_KEY, COOKIE_ACCESS_NAME,
                        REFRESH_TOKEN_EXPIRE_DAYS)
from app.db import get_db
from app.models import User
from app.time_utils import utcnow

security = HTTPBearer(auto_error=False)

TOKEN_EXCEPTION = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期",
                                headers={"WWW-Authenticate": "Bearer"})


def create_token(user: User, refresh: bool = False) -> str:
    lifetime = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS) if refresh else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user.id, "type": "refresh" if refresh else "access", "tv": user.token_version or 0,
               "exp": utcnow() + lifetime}
    return jwt.encode(payload, AUTH_SIGNING_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
                     db: Session = Depends(get_db)) -> User:
    token = credentials.credentials if credentials is not None else request.cookies.get(COOKIE_ACCESS_NAME)
    if not token:
        raise TOKEN_EXCEPTION
    try:
        payload = jwt.decode(token, AUTH_SIGNING_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from None
    except jwt.PyJWTError:
        raise TOKEN_EXCEPTION from None
    if payload.get("type") != "access":
        raise TOKEN_EXCEPTION
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise TOKEN_EXCEPTION
    # A changed or reset password, or a stopped account, ends every earlier session.
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="只有系统管理员可以执行此操作")
    return user
