"""TOTP, encrypted secrets and transaction-scoped one-use authentication state."""
import base64
from datetime import timedelta
import hashlib
import hmac
import os
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode
from uuid import uuid4

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, select, update

from app import config
from app.models import User, MfaChallenge, MfaRecoveryCode, AiApiToken
from app.services.change_log import log_change
from app.time_utils import utcnow

CHALLENGE_SECONDS = 300
ISSUER = '行序'


class MfaError(ValueError):
    pass


def mandatory(user):
    return config.PUBLIC_MODE and user.role in {'admin', 'pm'}


def required(user):
    return mandatory(user) or bool(getattr(user, 'mfa_enabled', False))


def session_allowed(user, payload):
    return not required(user) or (bool(getattr(user, 'mfa_enabled', False)) and payload.get('mfa') is True)


def agent_allowed(user, token):
    version = getattr(token, 'auth_version', None)
    if version is not None and version != (user.token_version or 0):
        return False
    return not required(user) or (bool(getattr(user, 'mfa_enabled', False)) and version == (user.token_version or 0))


def _cipher():
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b'xingxu-auth-mfa-v1', info=b'totp-secret').derive(config.SECRET_KEY.encode())
    return AESGCM(key)


def seal(user_id, secret):
    nonce = os.urandom(12)
    return base64.urlsafe_b64encode(nonce + _cipher().encrypt(nonce, secret.encode(), ('totp:' + user_id).encode())).decode()


def unseal(user_id, value):
    try:
        raw = base64.urlsafe_b64decode(value)
        return _cipher().decrypt(raw[:12], raw[12:], ('totp:' + user_id).encode()).decode()
    except (InvalidTag, ValueError, TypeError, UnicodeError):
        raise MfaError('二次验证密钥无法读取，请使用部署恢复流程') from None


def totp(secret, step, digits=6, algorithm='sha1'):
    key = base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack('>Q', step), algorithm).digest()
    offset = digest[-1] & 15
    return str((struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % (10 ** digits)).zfill(digits)


def matched_step(secret, code, *, last=-1):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
        raise MfaError('验证码无效、已使用或已过期，请等待下一组验证码')
    current = int(time.time()) // 30
    for step in (current, current - 1, current + 1):
        if step > last and step >= 0 and hmac.compare_digest(totp(secret, step), code):
            return step
    raise MfaError('验证码无效、已使用或已过期，请等待下一组验证码')


def lock_user(db, user_id):
    # Clear a prior authentication read transaction before upgrading SQLite to a
    # writer. The first no-op UPDATE locks the same account on both DB engines.
    db.rollback()
    result = db.execute(update(User).where(User.id == user_id).values(token_version=User.token_version).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise MfaError('登录步骤已失效，请重新登录')
    user = db.get(User, user_id, populate_existing=True)
    if not user or not user.is_active:
        raise MfaError('账号不可用，请重新登录')
    return user


def issue(db, user_id, purpose, login_key, *, expected_version=None):
    user = lock_user(db, user_id)
    if expected_version is not None and (user.token_version or 0) != expected_version:
        raise MfaError('账号已变化，请重新登录')
    if purpose == 'login' and not user.mfa_enabled:
        raise MfaError('验证状态已变化，请重新登录')
    if purpose == 'enroll' and (user.mfa_enabled or user.role not in {'admin', 'pm'}):
        raise MfaError('当前账号不能登记新的二次验证')
    return issue_locked(db, user, purpose, login_key)


def issue_locked(db, user, purpose, login_key):
    db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == user.id))
    row = MfaChallenge(id=str(uuid4()), user_id=user.id, purpose=purpose, token_version=user.token_version or 0,
                       login_key=login_key, expires_at=utcnow() + timedelta(seconds=CHALLENGE_SECONDS))
    db.add(row)
    token = jwt.encode({'sub': user.id, 'jti': row.id, 'purpose': purpose, 'tv': row.token_version,
                        'type': 'mfa_challenge', 'aud': 'xingxu-mfa', 'exp': row.expires_at}, config.AUTH_SIGNING_KEY, algorithm=config.ALGORITHM)
    log_change(db, None, 'user', user.id, 'mfa_challenge_issue', user.id, '签发五分钟限定用途验证步骤', new_value={'purpose': purpose})
    db.commit()
    return {'two_factor_required': True, 'setup_required': purpose != 'login', 'challenge': token, 'expires_in': CHALLENGE_SECONDS}


def challenge(db, token):
    try:
        payload = jwt.decode(token, config.AUTH_SIGNING_KEY, algorithms=[config.ALGORITHM], audience='xingxu-mfa')
        if payload.get('type') != 'mfa_challenge' or payload.get('purpose') not in {'login', 'enroll', 'replace'}:
            raise ValueError()
        row = db.get(MfaChallenge, payload.get('jti'))
        if not row or row.user_id != payload.get('sub') or row.token_version != payload.get('tv') or row.purpose != payload.get('purpose'):
            raise ValueError()
        return row
    except (jwt.PyJWTError, ValueError, TypeError):
        raise MfaError('登录步骤已过期或已取消，请重新登录') from None


def locked_challenge(db, token, purpose):
    row = challenge(db, token)
    identifier, user_id = row.id, row.user_id
    user = lock_user(db, user_id)
    row = db.get(MfaChallenge, identifier, populate_existing=True)
    if (not row or row.used_at or row.expires_at <= utcnow() or row.purpose not in purpose
            or row.token_version != (user.token_version or 0)):
        raise MfaError('登录步骤已过期或已使用，请重新登录')
    return user, row


def enrollment_start(db, token):
    user, row = locked_challenge(db, token, {'enroll', 'replace'})
    if row.purpose == 'enroll' and user.mfa_enabled:
        raise MfaError('账号已启用二次验证，请重新登录')
    if not row.pending_secret_encrypted:
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
        row.pending_secret_encrypted = seal(user.id, secret)
        log_change(db, None, 'user', user.id, 'mfa_setup_start', user.id, '生成待确认的加密认证器密钥')
        db.commit()
    else:
        secret = unseal(user.id, row.pending_secret_encrypted)
        db.commit()
    uri = 'otpauth://totp/' + quote(ISSUER + ':' + user.username, safe='') + '?' + urlencode({'secret': secret, 'issuer': ISSUER, 'algorithm': 'SHA1', 'digits': 6, 'period': 30})
    return {'secret': secret, 'otpauth_uri': uri, 'expires_in': max(0, int((row.expires_at - utcnow()).total_seconds()))}


def code_hash(user_id, code):
    normalized = code.strip().replace('-', '').lower()
    if not re.fullmatch(r'[a-f0-9]{32}', normalized):
        raise MfaError('恢复码无效或已使用')
    return hashlib.sha256(('xingxu-recovery-v1:' + user_id + ':' + normalized).encode()).hexdigest()


def use_recovery(db, user, code):
    digest = code_hash(user.id, code)
    row = db.execute(update(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id,
                     MfaRecoveryCode.code_hash == digest, MfaRecoveryCode.used_at.is_(None)).values(used_at=utcnow()).returning(MfaRecoveryCode.id)).first()
    if not row:
        raise MfaError('恢复码无效或已使用')


def new_codes(db, user):
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    result = []
    for _ in range(10):
        raw = secrets.token_hex(16)
        code = '-'.join(raw[i:i + 8] for i in range(0, 32, 8))
        db.add(MfaRecoveryCode(id=str(uuid4()), user_id=user.id, code_hash=code_hash(user.id, code)))
        result.append(code)
    return result


def consume_totp(user, code):
    user.mfa_last_step = matched_step(unseal(user.id, user.mfa_secret_encrypted), code, last=user.mfa_last_step)


def verify_login(db, token, otp='', recovery_code=''):
    user, row = locked_challenge(db, token, {'login'})
    if not user.mfa_enabled or bool(otp) == bool(recovery_code):
        raise MfaError('请输入验证码或一枚恢复码')
    if recovery_code:
        use_recovery(db, user, recovery_code)
        log_change(db, None, 'user', user.id, 'mfa_recovery_use', user.id, '使用一次性恢复码完成二次验证')
    else:
        consume_totp(user, otp)
        log_change(db, None, 'user', user.id, 'mfa_login', user.id, '使用当前未重放的认证器验证码完成登录')
    row.used_at = utcnow()
    version = user.token_version or 0
    db.commit()
    return user, version


def enrollment_confirm(db, token, otp):
    user, row = locked_challenge(db, token, {'enroll', 'replace'})
    if not row.pending_secret_encrypted or (row.purpose == 'enroll' and user.mfa_enabled):
        raise MfaError('请重新开始二次验证登记')
    secret = unseal(user.id, row.pending_secret_encrypted)
    step = matched_step(secret, otp)
    user.mfa_enabled = True
    user.mfa_secret_encrypted = row.pending_secret_encrypted
    user.mfa_last_step = step
    user.token_version = (user.token_version or 0) + 1
    codes = new_codes(db, user)
    db.execute(update(AiApiToken).where(AiApiToken.user_id == user.id).values(is_active=False))
    row.used_at = utcnow(); row.pending_secret_encrypted = None
    log_change(db, None, 'user', user.id, 'mfa_enable' if row.purpose == 'enroll' else 'mfa_replace', user.id,
               '确认二次验证登记；撤销旧会话和外部凭据', new_value={'enabled': True, 'recovery_codes': 10})
    version = user.token_version or 0
    db.commit()
    return user, codes, version


def disable(db, user_id, otp, *, expected_version=None):
    user = lock_user(db, user_id)
    if expected_version is not None and (user.token_version or 0) != expected_version:
        raise MfaError('账号已变化，请重新登录')
    if mandatory(user):
        raise MfaError('公开部署的管理员和项目经理不能关闭二次验证')
    if not user.mfa_enabled:
        raise MfaError('账号未启用二次验证')
    consume_totp(user, otp)
    user.mfa_enabled = False; user.mfa_secret_encrypted = None; user.mfa_last_step = -1
    user.token_version = (user.token_version or 0) + 1
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == user.id))
    db.execute(update(AiApiToken).where(AiApiToken.user_id == user.id).values(is_active=False))
    log_change(db, None, 'user', user.id, 'mfa_disable', user.id, '使用当前验证码关闭二次验证；撤销旧会话和外部凭据')
    db.commit()


def regenerate(db, user_id, otp, *, expected_version=None):
    user = lock_user(db, user_id)
    if expected_version is not None and (user.token_version or 0) != expected_version:
        raise MfaError('账号已变化，请重新登录')
    if not user.mfa_enabled:
        raise MfaError('账号未启用二次验证')
    consume_totp(user, otp)
    codes = new_codes(db, user)
    log_change(db, None, 'user', user.id, 'mfa_codes_refresh', user.id,
               '重新生成恢复码；旧恢复码立即失效', new_value={'count': 10})
    db.commit()
    return codes


def recover_login(db, token, recovery_code):
    """Password-bound login challenge + last recovery code can rebind safely.

    No business session is issued before a new authenticator is confirmed.
    The existing authenticator stays active until that transaction commits.
    """
    user, row = locked_challenge(db, token, {'login'})
    if not user.mfa_enabled:
        raise MfaError('账号状态已变化，请重新登录')
    use_recovery(db, user, recovery_code)
    log_change(db, None, 'user', user.id, 'mfa_recovery_begin', user.id,
               '密码及一次性恢复码确认重新绑定；原验证持续生效')
    return issue_locked(db, user, 'replace', row.login_key)


def cancel(db, token):
    user, row = locked_challenge(db, token, {'login', 'enroll', 'replace'})
    row.used_at = utcnow(); row.pending_secret_encrypted = None
    log_change(db, None, 'user', user.id, 'mfa_cancel', user.id, '取消限定用途验证步骤并销毁待确认密钥')
    db.commit()


def host_reset(db, user_id):
    """Trusted local host operation; there is deliberately no web reset route."""
    user = lock_user(db, user_id)
    user.mfa_enabled = False; user.mfa_secret_encrypted = None; user.mfa_last_step = -1
    user.token_version = (user.token_version or 0) + 1
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    db.execute(delete(MfaChallenge).where(MfaChallenge.user_id == user.id))
    db.execute(update(AiApiToken).where(AiApiToken.user_id == user.id).values(is_active=False))
    log_change(db, None, 'user', user.id, 'mfa_host_reset', None,
               '受信宿主操作员重置二次验证；撤销所有会话及外部凭据，公开部署下次登录必须重新登记')
    db.commit()
