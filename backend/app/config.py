"""Application configuration loaded from environment variables."""

import os
import sys
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
APP_VERSION = os.getenv("APP_VERSION", "4.0.0")

# Data directory (SQLite DB, uploads)
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/agvpm.db")

# A staged restore must run before the SQLite database file and SECRET_KEY are
# consumed. It is SQLite-only: on the PostgreSQL deployment the app-level staged
# restore cannot restore the database (docker/scripts/restore.sh + pg_restore is
# the supported path), and applying a SQLite snapshot here would silently replace
# uploads/secret.key while leaving the PG data untouched — so only run it for SQLite.
# Trusted host entrypoints set private process flags before importing config;
# neither the update bridge nor account recovery may consume a live pending restore.
if (DATABASE_URL.startswith("sqlite")
        and not getattr(sys, "_xingxu_host_update_bridge", False)
        and not getattr(sys, "_xingxu_host_auth_recovery", False)):
    from app.services.restore_bootstrap import apply_pending_restore  # noqa: E402
    apply_pending_restore(DATA_DIR)

# Auth
# SECRET_KEY：env 优先；未设置则从 DATA_DIR/secret.key 读取或自动生成（持久化，重启不失效）。
# 生产部署建议显式设置 SECRET_KEY 环境变量；首次启动后拷贝 data/secret.key 即可带到 NAS。
def _load_secret_key() -> str:
    env_key = os.getenv("SECRET_KEY")
    if env_key:
        return env_key
    key_file = DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_text().strip()
    import secrets
    generated = secrets.token_urlsafe(48)
    try:
        key_file.write_text(generated)
        key_file.chmod(0o600)
    except OSError:
        pass  # 只读文件系统时退回内存随机（重启后 token 失效，可接受）
    return generated


SECRET_KEY = _load_secret_key()
# Sessions can be revoked by rotating this key independently of saved encrypted
# credentials, TOTP secrets and retirement exports. Empty retains legacy setups.
AUTH_SIGNING_KEY = os.getenv("AUTH_SIGNING_KEY", "").strip() or SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Upload
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
def _upload_mb(raw):
    # The largest single file, in MiB. 0 = no limit.
    try:
        value = int(raw)
        return value if 0 <= value <= 1048576 else 200
    except (TypeError, ValueError):
        return 200


MAX_UPLOAD_MB = _upload_mb(os.getenv("MAX_UPLOAD_MB", "200") or "200")
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024  # 0 = no limit
MAX_IMPORT_BYTES = 10 * 1024 * 1024  # an Excel file read into memory
MAX_BACKUP_UPLOAD_SIZE = int(os.getenv("MAX_BACKUP_UPLOAD_MB", "2048")) * 1024 * 1024

# Timezone（默认东八区；多地区现场可通过环境变量覆盖）
TIMEZONE = os.getenv("TIMEZONE", "Asia/Shanghai")

# Optional cross-origin development clients. Production is same-origin and
# therefore needs no CORS headers by default.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
# Host 校验白名单：精确主机/域名、*.domain 子域通配、IP 网段（CIDR，如 192.168.1.0/24）。
# 由 app/middleware.py TrustedHostsMiddleware 解释；未命中条目仍 400 Invalid host header。
PUBLIC_MODE = os.getenv("PUBLIC_MODE", "0") == "1"
TRUSTED_HOSTS = [host.strip() for host in os.getenv("TRUSTED_HOSTS", "*").split(",")]
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "0") == "1"
FORWARDED_ALLOW_IPS = os.getenv("FORWARDED_ALLOW_IPS", "")


def validate_public_mode() -> None:
    from app.services.public_security import validate_public_settings
    validate_public_settings(public_mode=PUBLIC_MODE, cookie_secure=COOKIE_SECURE,
                             force_https=FORCE_HTTPS, trusted_hosts=TRUSTED_HOSTS,
                             forwarded_allow_ips=FORWARDED_ALLOW_IPS)

# HttpOnly Cookie 认证（P2-安全）：浏览器会话走 SameSite=Lax + CSRF 双提交。
# COOKIE_SECURE=1 时给 Cookie 打 Secure 标记——必须在前置 HTTPS 反代下开启
# （本地 HTTP 演示默认 0，否则浏览器不写 Cookie）。
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").strip().lower() or "lax"
COOKIE_ACCESS_NAME = "agvpm_access"
COOKIE_REFRESH_NAME = "agvpm_refresh"
COOKIE_CSRF_NAME = "agvpm_csrf"
COOKIE_SESSION_MARKER = "agvpm_session"

# Rows and projects in the trash are removed for good after this many days.
TRASH_DAYS = 30
