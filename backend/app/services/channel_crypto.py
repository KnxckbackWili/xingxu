"""通知渠道凭据加密（Webhook / 加签 Secret 落库）。

使用依赖中现成的 cryptography：
- HKDF-SHA256 从稳定 SECRET_KEY（env 或 DATA_DIR/secret.key，见 config._load_secret_key）
  派生 32 字节子密钥，domain info 固定为 b"notification-channel-credentials"；
- Fernet（AES-128-CBC + HMAC-SHA256，自带版本/时间戳/认证）加密，urlsafe-base64 存储。
同一 SECRET_KEY 下跨进程/重启/备份恢复均可解密；密钥不匹配抛 InvalidToken（对外包装为
ValueError）。该能力分支从未上线，不存在旧密文格式兼容问题。
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app import config

_HKDF_SALT = b"agvpm-notification-channel-v1"
_HKDF_INFO = b"notification-channel-credentials"


def _fernet() -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(config.SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_text(plaintext: str) -> str:
    """加密字符串；空串返回空串（调用方以空串表示"未设置"）。"""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    """解密字符串；空串返回空串；篡改/密钥不匹配抛 ValueError（原因为 InvalidToken）。"""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise ValueError("密文校验失败（密钥不匹配或被篡改）") from error
