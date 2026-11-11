"""Sign in, refresh, sign out, who am I, change my password."""
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.access import public
from app.db import _is_sqlite, get_db
from app.deps import create_token, get_current_user
from app.models import User
from app.services.change_log import log_change
from app.services.cookies import clear_auth_cookies, set_auth_cookies
from app.time_utils import utcnow

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
router = APIRouter(prefix="/auth", tags=["登录"])

_LOGIN_WINDOW = 15 * 60
_LOGIN_LIMIT = 8
_TOO_MANY = "登录失败次数过多，请 15 分钟后再试"
# One process (SQLite): failures in memory. PostgreSQL: a shared table, so every web worker
# counts together and a restart does not reset the window.
_login_failures: dict[str, list[float]] = {}
_login_lock = threading.Lock()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=1, max_length=4096)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def user_payload(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "role": user.role, "is_active": user.is_active}


def _login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.strip().lower()}"[:200]


def _check_login_limit(key: str, db: Session) -> None:
    if _is_sqlite:
        now = time.monotonic()
        with _login_lock:
            recent = [stamp for stamp in _login_failures.get(key, []) if now - stamp < _LOGIN_WINDOW]
            if recent:
                _login_failures[key] = recent
            else:
                _login_failures.pop(key, None)
            blocked = len(recent) >= _LOGIN_LIMIT
    else:
        row = db.execute(text("SELECT count FROM login_failures WHERE key = :key AND bucket = :bucket"),
                         {"key": key, "bucket": int(time.time()) // _LOGIN_WINDOW}).fetchone()
        blocked = row is not None and row[0] >= _LOGIN_LIMIT
    if blocked:
        raise HTTPException(status_code=429, detail=_TOO_MANY)


def _record_login(key: str, success: bool, db: Session) -> None:
    if _is_sqlite:
        with _login_lock:
            if success:
                _login_failures.pop(key, None)
            else:
                if key not in _login_failures and len(_login_failures) >= 10_000:
                    _login_failures.pop(next(iter(_login_failures)))
                _login_failures.setdefault(key, []).append(time.monotonic())
        return
    if success:
        db.execute(text("DELETE FROM login_failures WHERE key = :key"), {"key": key})
        db.commit()
        return
    bucket, now = int(time.time()) // _LOGIN_WINDOW, utcnow()
    db.execute(text("DELETE FROM login_failures WHERE bucket < :oldest"), {"oldest": bucket - 1})
    db.execute(text("INSERT INTO login_failures (id, key, bucket, count, updated_at) VALUES (:id, :key, :bucket, 0, :now) "
                    "ON CONFLICT (key, bucket) DO NOTHING"),
               {"id": str(uuid.uuid4()), "key": key, "bucket": bucket, "now": now})
    db.commit()
    # The row lock makes exactly _LOGIN_LIMIT concurrent failures succeed in counting.
    row = db.execute(text("UPDATE login_failures SET count = count + 1, updated_at = :now "
                          "WHERE key = :key AND bucket = :bucket AND count < :limit RETURNING count"),
                     {"key": key, "bucket": bucket, "limit": _LOGIN_LIMIT, "now": now}).fetchone()
    db.commit()
    if row is None:
        raise HTTPException(status_code=429, detail=_TOO_MANY)


def reset_login_failures() -> None:
    """Forget every counted failure (test isolation)."""
    with _login_lock:
        _login_failures.clear()
    if not _is_sqlite:
        from app.db import SessionLocal
        with SessionLocal() as db:
            db.execute(text("DELETE FROM login_failures"))
            db.commit()


def _session(user: User, response: Response) -> dict:
    access, refresh = create_token(user), create_token(user, refresh=True)
    set_auth_cookies(response, access, refresh)
    response.headers["Cache-Control"] = "no-store"
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "user": user_payload(user)}


@router.post("/login")
@public("登录入口：凭用户名和密码建立会话，失败按来源和用户名限速")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    key = _login_key(request, data.username)
    _check_login_limit(key, db)
    user = db.query(User).filter(User.username == data.username.strip()).first()
    if user is None or not pwd_context.verify(data.password, user.password_hash):
        _record_login(key, False, db)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被停用")
    _record_login(key, True, db)
    return _session(user, response)


@router.post("/refresh")
@public("会话刷新入口：校验刷新令牌、账号状态和令牌版本")
def refresh_token(data: RefreshRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    import jwt
    from app.config import ALGORITHM, AUTH_SIGNING_KEY, COOKIE_REFRESH_NAME

    def reject(detail: str) -> JSONResponse:
        # A failed refresh means the session is over: clear its cookies, or the page would
        # keep believing it is signed in and loop between the app and the sign-in page.
        failed = JSONResponse(status_code=401, content={"detail": detail})
        clear_auth_cookies(failed)
        return failed

    raw = data.refresh_token or request.cookies.get(COOKIE_REFRESH_NAME)
    if not raw:
        return reject("无效的刷新令牌")
    try:
        payload = jwt.decode(raw, AUTH_SIGNING_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return reject("无效的刷新令牌")
    if payload.get("type") != "refresh":
        return reject("无效的刷新令牌")
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        return reject("账号不存在或已停用")
    if payload.get("tv", 0) != (user.token_version or 0):
        return reject("登录已过期，请重新登录")
    return _session(user, response)


@router.post("/logout")
@public("只清除当前浏览器的会话 Cookie")
def logout(response: Response):
    clear_auth_cookies(response)
    return {"message": "已退出登录"}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_payload(user)


@router.put("/password")
def change_password(data: PasswordChange, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not pwd_context.verify(data.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = pwd_context.hash(data.new_password)
    user.token_version = (user.token_version or 0) + 1  # every other device is signed out
    log_change(db, None, "user", user.id, "password", user, "修改自己的密码", row_label=user.display_name)
    db.commit()
    db.refresh(user)
    return {"message": "密码已修改", **_session(user, response)}
