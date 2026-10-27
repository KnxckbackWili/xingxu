"""Auth routes: login, refresh, me, change password."""

import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission_exempt
from app.db import _is_sqlite, get_db
from app.deps import create_token, get_current_user
from app.models import User
from app.schemas.auth import (LoginRequest, RefreshRequest, TokenResponse, PasswordChangeRequest,
    MfaChallengeRequest, MfaVerifyRequest, MfaProof, MfaPasswordProof, MfaRecoveryProof)
from app.services import two_factor as mfa
from app.services.change_log import log_change
from app.time_utils import utcnow

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/auth", tags=["认证"])

_LOGIN_WINDOW = 15 * 60
_LOGIN_LIMIT = 8

# ---- SQLite/单进程：进程内滑动窗口（原语义，本地与测试） ----
_login_failures: dict[str, list[float]] = {}
_login_lock = threading.Lock()

# ---- PostgreSQL 共享计数（T025）：复用 T006 共享桶设计 ----
# 固定窗口桶 + 原子递增（UPDATE ... WHERE count < :limit RETURNING）：
# 多 worker（WEB_CONCURRENCY>=2）共用同一计数、容器重启不绕过窗口、不同
# key（host:username）隔离。与导出限流不同：仅统计失败；成功登录清空该 key。


def _user_payload(db: Session, user: User) -> dict:
    from app.models import Project
    from app.services.system_permissions import effective_permissions
    from app.services.scope import active_co_manager
    has_co_manager_projects = any(active_co_manager(project, user.id) for project in db.query(Project).filter(Project.deleted_at.is_(None)).all())  # C8-4：软删除项目不算协管
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "phone": user.phone or "",
        "email": user.email or "",
        "is_active": user.is_active,
        "has_co_manager_projects": has_co_manager_projects,
        "system_permissions": effective_permissions(user),
        "permission_overrides": dict(user.permission_overrides or {}),
        "permission_version": user.permission_version or 0,
        "two_factor_enabled": bool(user.mfa_enabled),
        "two_factor_required": mfa.mandatory(user),
    }


def _login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username.strip().lower()}"


def _mem_check_login_limit(key: str) -> None:
    now = time.monotonic()
    with _login_lock:
        failures = [stamp for stamp in _login_failures.get(key, []) if now - stamp < _LOGIN_WINDOW]
        if failures:
            _login_failures[key] = failures
        else:
            _login_failures.pop(key, None)
        if len(failures) >= _LOGIN_LIMIT:
            raise HTTPException(status_code=429, detail="登录失败次数过多，请 15 分钟后再试")


def _mem_record_login(key: str, success: bool) -> None:
    with _login_lock:
        if success:
            _login_failures.pop(key, None)
        else:
            if key not in _login_failures and len(_login_failures) >= 10_000:
                _login_failures.pop(next(iter(_login_failures)))
            _login_failures.setdefault(key, []).append(time.monotonic())


def _pg_login_check(db: Session, key: str) -> None:
    """PG 共享：当前桶失败数 >= 阈值 → 429（预检，避免对锁定账号做 bcrypt）。"""
    bucket = int(time.time()) // _LOGIN_WINDOW
    row = db.execute(text(
        "SELECT count FROM login_failure_buckets "
        "WHERE key = :key AND bucket = :bucket AND \"window\" = :window"
    ), {"key": key, "bucket": bucket, "window": _LOGIN_WINDOW}).fetchone()
    if row is not None and row[0] >= _LOGIN_LIMIT:
        raise HTTPException(status_code=429, detail="登录失败次数过多，请 15 分钟后再试")


def _pg_login_record(db: Session, key: str, success: bool) -> None:
    """PG 共享：成功清空该 key 全部失败计数；失败原子递增（并发安全）。

    1. 清理该 key 早于上一桶的过期桶（防无限膨胀）；
    2. INSERT ... ON CONFLICT DO NOTHING 幂等建行；
    3. UPDATE ... WHERE count < :limit RETURNING count 原子递增——
       PG 行锁保证并发下恰好 limit 次成功，第 limit+1 次起返回空 → 429。
    """
    now = utcnow()
    if success:
        db.execute(text(
            "DELETE FROM login_failure_buckets WHERE key = :key AND \"window\" = :window"
        ), {"key": key, "window": _LOGIN_WINDOW})
        db.commit()
        return
    bucket = int(time.time()) // _LOGIN_WINDOW
    # 注意：`window` 是 PostgreSQL 保留字，必须用双引号引用列名。
    db.execute(text(
        "DELETE FROM login_failure_buckets "
        "WHERE key = :key AND \"window\" = :window AND bucket < :min_bucket"
    ), {"key": key, "window": _LOGIN_WINDOW, "min_bucket": bucket - 1})
    db.commit()
    db.execute(text(
        "INSERT INTO login_failure_buckets (id, key, bucket, \"window\", count, created_at, updated_at) "
        "VALUES (:id, :key, :bucket, :window, 0, :now, :now) "
        "ON CONFLICT (key, bucket, \"window\") DO NOTHING"
    ), {"id": str(uuid.uuid4()), "key": key, "bucket": bucket,
        "window": _LOGIN_WINDOW, "now": now})
    db.commit()
    row = db.execute(text(
        "UPDATE login_failure_buckets SET count = count + 1, updated_at = :now "
        "WHERE key = :key AND bucket = :bucket AND \"window\" = :window AND count < :limit "
        "RETURNING count"
    ), {"key": key, "bucket": bucket, "window": _LOGIN_WINDOW,
        "limit": _LOGIN_LIMIT, "now": now}).fetchone()
    db.commit()
    if row is None:
        raise HTTPException(status_code=429, detail="登录失败次数过多，请 15 分钟后再试")


def _check_login_limit(key: str, db: Session) -> None:
    if _is_sqlite:
        _mem_check_login_limit(key)
    else:
        _pg_login_check(db, key)


def _record_login(key: str, success: bool, db: Session) -> None:
    if _is_sqlite:
        _mem_record_login(key, success)
    else:
        _pg_login_record(db, key, success)


def reset_login_failures() -> None:
    """清空登录失败计数（测试隔离用）：SQLite 清内存；PG 清共享表。"""
    with _login_lock:
        _login_failures.clear()
    if not _is_sqlite:
        from app.db import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM login_failure_buckets"))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def _sensitive(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'


def _session(db, user, response, *, verified=False, version=None, recovery_codes=None):
    from app.services.cookies import set_auth_cookies
    access = create_token(user, mfa_verified=verified, verified_version=version)
    refresh = create_token(user, refresh=True, mfa_verified=verified, verified_version=version)
    set_auth_cookies(response, access, refresh); _sensitive(response)
    result = TokenResponse(access_token=access, refresh_token=refresh, user=_user_payload(db, user)).model_dump()
    if recovery_codes is not None:
        result['recovery_codes'] = recovery_codes
    return result


def _mfa_account_key(user_id):
    return 'mfa:' + user_id


def _challenge_limit(db, token):
    row = mfa.challenge(db, token)
    _check_login_limit(row.login_key, db)
    _check_login_limit(_mfa_account_key(row.user_id), db)
    return row.login_key, _mfa_account_key(row.user_id)


def _mfa_failure(db, keys, error):
    db.rollback()
    for key in dict.fromkeys(keys):
        _record_login(key, False, db)
    raise HTTPException(status_code=401, detail=str(error)) from None


async def _mfa_request_token(request: Request):
    """A challenge is this entry point's credential, including without a session."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(401, '请提供有效的登录验证步骤') from None
    token = body.get('challenge') if isinstance(body, dict) else None
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise HTTPException(401, '请提供有效的登录验证步骤')
    return token


class _MfaChallengeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def authenticate_body(request: Request):
            # FastAPI decodes JSON before resolving dependencies. Reject absent
            # credentials even for malformed JSON, then retain its normal schema
            # validation after the read-only challenge dependency below.
            await _mfa_request_token(request)
            return await handler(request)

        return authenticate_body


def _mfa_challenge_auth(*purposes):
    async def authenticate(request: Request, db: Session = Depends(get_db)):
        token = await _mfa_request_token(request)
        try:
            row = mfa.challenge(db, token)
            user = db.get(User, row.user_id)
            if (row.purpose not in purposes or row.used_at or row.expires_at <= utcnow()
                    or not user or not user.is_active or row.token_version != (user.token_version or 0)):
                raise mfa.MfaError('登录步骤已过期或已取消，请重新登录')
        except mfa.MfaError as error:
            raise HTTPException(401, str(error)) from None
        # No mutation, factor consumption, rate accounting or business JWT here.
        # The service must still lock and recheck every fact before its write.

    return Depends(authenticate)


_mfa_challenge_router = APIRouter(route_class=_MfaChallengeRoute)


@router.post('/login')
@route_permission_exempt('公开登录入口，密码成功后仍须完成二次验证或限定用途登记')
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    key = _login_key(request, data.username)
    _check_login_limit(key, db)
    user = db.query(User).filter(User.username == data.username).first()
    if user is None or not pwd_context.verify(data.password, user.password_hash):
        _record_login(key, False, db)
        raise HTTPException(status_code=401, detail='用户名或密码错误')
    if not user.is_active:
        raise HTTPException(status_code=403, detail='账号已被停用')
    version = user.token_version or 0
    if mfa.required(user):
        _check_login_limit(_mfa_account_key(user.id), db)
        purpose = 'login' if user.mfa_enabled else 'enroll'
        try:
            result = mfa.issue(db, user.id, purpose, key, expected_version=version)
        except mfa.MfaError as error:
            _mfa_failure(db, [key], error)
        from app.services.cookies import clear_auth_cookies
        clear_auth_cookies(response); _sensitive(response)
        return result
    _record_login(key, True, db)
    return _session(db, user, response, version=version)


@router.post("/refresh", response_model=TokenResponse)
@route_permission_exempt('会话刷新入口，校验刷新令牌和账号状态')
def refresh_token(data: RefreshRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    import jwt
    from app.config import AUTH_SIGNING_KEY, ALGORITHM, COOKIE_REFRESH_NAME
    from app.services.cookies import set_auth_cookies, clear_auth_cookies

    def _reject(detail: str) -> JSONResponse:
        # HYPE-56：刷新失败说明会话确已失效。必须清掉 HttpOnly 会话 cookie——
        # 否则旧 agvpm_session 标记残留，前端 isAuthed() 恒真，登录页反复
        # fetchMe→401→refresh→失败→重定向，把登录页自身写进 next 形成路由级死循环。
        # 返回 JSONResponse 而非 raise HTTPException：raise 会丢弃 response 上已设置的
        # Set-Cookie（已实测），导致旧 cookie 永远清不掉。
        resp = JSONResponse(status_code=401, content={"detail": detail})
        clear_auth_cookies(resp)
        return resp

    # 刷新 token 来源：优先请求体（API 客户端），其次 HttpOnly Cookie（浏览器会话）
    raw_token = data.refresh_token or request.cookies.get(COOKIE_REFRESH_NAME)
    if not raw_token:
        return _reject("无效的刷新令牌")
    try:
        payload = jwt.decode(raw_token, AUTH_SIGNING_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return _reject("无效的刷新令牌")
        user = db.get(User, payload.get("sub"))
        if user is None or not user.is_active:
            return _reject("账号不存在或已停用")
        if payload.get("tv", 0) != (user.token_version or 0):
            return _reject("登录已过期，请重新登录")
    except jwt.PyJWTError:
        return _reject("无效的刷新令牌")
    if not mfa.session_allowed(user, payload):
        return _reject("此账号需要完成二次验证，请重新登录")
    return _session(db, user, response, verified=payload.get("mfa") is True, version=payload.get("tv", 0))


@router.post("/logout")
@route_permission_exempt('只清除当前浏览器会话Cookie')
def logout(response: Response):
    """登出：清除 HttpOnly 会话 Cookie。响应体仍返回成功，兼容旧前端。"""
    from app.services.cookies import clear_auth_cookies
    clear_auth_cookies(response)
    return {"message": "已登出"}


@router.get("/me", response_model=dict)
@route_permission_exempt('只读取已认证账号本人的会话资料')
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_payload(db, user)


@router.put("/password")
@route_permission_exempt('本人改密，处理器校验当前密码并撤销旧令牌', readonly_session=True)
def change_password(
    data: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not pwd_context.verify(data.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.password_hash = pwd_context.hash(data.new_password)
    # 令牌版本 +1：所有已签发的 access/refresh token 立即失效
    user.token_version = (user.token_version or 0) + 1
    log_change(db, None, "user", user.id, "change_password", user.id, "本人修改密码并撤销旧会话")
    db.commit()
    return {"message": "密码修改成功"}


@router.get('/2fa')
@route_permission_exempt('本人二次验证状态，不返回密钥或恢复码', readonly_session=True)
def mfa_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import MfaRecoveryCode
    return {'enabled': bool(user.mfa_enabled), 'required': mfa.mandatory(user),
            'can_enroll': user.role in {'admin', 'pm'},
            'recovery_codes_remaining': db.query(MfaRecoveryCode).filter_by(user_id=user.id, used_at=None).count()}


@_mfa_challenge_router.post('/2fa/verify', dependencies=[_mfa_challenge_auth('login')])
@route_permission_exempt('限定用途登录challenge；原子验证一次TOTP或恢复码后才签发完整会话')
def mfa_login(data: MfaVerifyRequest, response: Response, db: Session = Depends(get_db)):
    token = data.challenge.get_secret_value()
    try:
        keys = _challenge_limit(db, token)
    except mfa.MfaError as error:
        raise HTTPException(401, str(error)) from None
    try:
        user, version = mfa.verify_login(db, token, data.otp.get_secret_value(), data.recovery_code.get_secret_value())
    except mfa.MfaError as error:
        _mfa_failure(db, keys, error)
    for key in keys: _record_login(key, True, db)
    return _session(db, user, response, verified=True, version=version)


@_mfa_challenge_router.post('/2fa/enroll/start', dependencies=[_mfa_challenge_auth('enroll', 'replace')])
@route_permission_exempt('仅有效登记challenge可读取本次待确认密钥，无业务会话')
def mfa_enrollment_start(data: MfaChallengeRequest, response: Response, db: Session = Depends(get_db)):
    token = data.challenge.get_secret_value()
    try:
        keys = _challenge_limit(db, token)
        result = mfa.enrollment_start(db, token)
    except mfa.MfaError as error:
        db.rollback(); raise HTTPException(401, str(error)) from None
    _sensitive(response)
    return result


@_mfa_challenge_router.post('/2fa/enroll/confirm', dependencies=[_mfa_challenge_auth('enroll', 'replace')])
@route_permission_exempt('限定用途登记challenge及当前TOTP双重确认，原子启用并签发已验证会话')
def mfa_enrollment_confirm(data: MfaVerifyRequest, response: Response, db: Session = Depends(get_db)):
    token = data.challenge.get_secret_value()
    try:
        keys = _challenge_limit(db, token)
    except mfa.MfaError as error:
        raise HTTPException(401, str(error)) from None
    try:
        user, codes, version = mfa.enrollment_confirm(db, token, data.otp.get_secret_value())
    except mfa.MfaError as error:
        _mfa_failure(db, keys, error)
    for key in keys: _record_login(key, True, db)
    return _session(db, user, response, verified=True, version=version, recovery_codes=codes)


@router.post('/2fa/setup')
@route_permission_exempt('本人当前密码确认后开始可选二次验证登记', readonly_session=True)
def mfa_setup(data: MfaPasswordProof, request: Request, response: Response,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = _login_key(request, user.username)
    _check_login_limit(key, db); _check_login_limit(_mfa_account_key(user.id), db)
    if not pwd_context.verify(data.password.get_secret_value(), user.password_hash):
        _record_login(key, False, db); raise HTTPException(401, '当前密码错误')
    try:
        result = mfa.issue(db, user.id, 'enroll', key, expected_version=user.token_version or 0)
    except mfa.MfaError as error:
        _mfa_failure(db, [key], error)
    _sensitive(response)
    return result


@router.post('/2fa/disable')
@route_permission_exempt('仅本人已验证会话及当前未使用TOTP可关闭，公开强制账号不能关闭', readonly_session=True)
def mfa_disable(data: MfaProof, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = _mfa_account_key(user.id); _check_login_limit(key, db)
    try: mfa.disable(db, user.id, data.otp.get_secret_value(), expected_version=user.token_version or 0)
    except mfa.MfaError as error: _mfa_failure(db, [key], error)
    from app.services.cookies import clear_auth_cookies
    clear_auth_cookies(response); _sensitive(response)
    return {'message': '二次验证已关闭，请重新登录'}


@router.post('/2fa/recovery-codes')
@route_permission_exempt('本人当前未使用TOTP确认后替换恢复码，明文仅本次响应', readonly_session=True)
def mfa_codes(data: MfaProof, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = _mfa_account_key(user.id); _check_login_limit(key, db)
    try: codes = mfa.regenerate(db, user.id, data.otp.get_secret_value(), expected_version=user.token_version or 0)
    except mfa.MfaError as error: _mfa_failure(db, [key], error)
    _sensitive(response)
    return {'recovery_codes': codes}


@router.post('/2fa/recover')
@route_permission_exempt('本人密码及额外一次性恢复码确认后，仅发重新绑定challenge，旧二次验证持续生效', readonly_session=True)
def mfa_recover(data: MfaRecoveryProof, request: Request, response: Response,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = _mfa_account_key(user.id); _check_login_limit(key, db)
    if not pwd_context.verify(data.password.get_secret_value(), user.password_hash):
        _record_login(key, False, db); raise HTTPException(401, '当前密码错误')
    expected = user.token_version or 0
    try:
        actor = mfa.lock_user(db, user.id)
        if not actor.mfa_enabled or (actor.token_version or 0) != expected:
            raise mfa.MfaError('账号已变化，请重新登录')
        mfa.use_recovery(db, actor, data.recovery_code.get_secret_value())
        log_change(db, None, 'user', actor.id, 'mfa_recovery_begin', actor.id, '密码及一次性恢复码确认重新绑定；原验证持续生效')
        result = mfa.issue_locked(db, actor, 'replace', _login_key(request, actor.username))
    except mfa.MfaError as error: _mfa_failure(db, [key], error)
    _sensitive(response)
    return result


@_mfa_challenge_router.post('/2fa/recover/start', dependencies=[_mfa_challenge_auth('login')])
@route_permission_exempt('密码验证后的登录challenge及一枚恢复码，只允许重新绑定登记，不能访问业务')
def mfa_login_recover(data: MfaVerifyRequest, response: Response, db: Session = Depends(get_db)):
    token = data.challenge.get_secret_value()
    try:
        keys = _challenge_limit(db, token)
    except mfa.MfaError as error:
        raise HTTPException(401, str(error)) from None
    try:
        result = mfa.recover_login(db, token, data.recovery_code.get_secret_value())
    except mfa.MfaError as error:
        _mfa_failure(db, keys, error)
    _sensitive(response)
    return result


@_mfa_challenge_router.post('/2fa/cancel', dependencies=[_mfa_challenge_auth('login', 'enroll', 'replace')])
@route_permission_exempt('有效限定用途challenge仅可取消自身并销毁本次待确认密钥')
def mfa_cancel(data: MfaChallengeRequest, response: Response, db: Session = Depends(get_db)):
    try: mfa.cancel(db, data.challenge.get_secret_value())
    except mfa.MfaError:
        db.rollback()
    _sensitive(response)
    return {'message': '验证步骤已取消'}


router.include_router(_mfa_challenge_router)
