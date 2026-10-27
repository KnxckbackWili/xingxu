"""Application configuration loaded from environment variables."""

import os
import sys
from pathlib import Path
from typing import Optional

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
APP_VERSION = os.getenv("APP_VERSION", "3.0.0")

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
    try:
        value=int(raw)
        return value if 1<=value<=1048576 else 2048
    except (TypeError,ValueError):return 2048

MAX_UPLOAD_MB = _upload_mb(os.getenv('MAX_UPLOAD_MB','2048'))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
# Buffered import/legacy multipart readers must never allocate a multi-GiB body.
# Project evidence files use the streaming resumable protocol and MAX_UPLOAD_BYTES.
MAX_BUFFERED_UPLOAD_SIZE = 10 * 1024 * 1024
MAX_UPLOAD_SIZE = min(MAX_UPLOAD_BYTES,MAX_BUFFERED_UPLOAD_SIZE)
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
UPLOAD_SESSION_TTL_DAYS = 7
MAX_BACKUP_UPLOAD_SIZE = int(os.getenv("MAX_BACKUP_UPLOAD_MB", "2048")) * 1024 * 1024

# Default working hours per day
DEFAULT_WORK_HOURS = 8

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

# 定时报告（APScheduler；默认关，测试/本地开发不启动线程）
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "0") == "1"
# C8-4：治理软删除的保留期（天）——超过保留期由每日清理任务物理删除（数据可恢复窗口）
# Deprecated #85: ignored; recycled projects never expire automatically.
SOFT_DELETE_RETENTION_DAYS = 30


# T24：问题按性质使用经过小时阈值，每分钟扫描；仅关闭/作废算闭环。
# 普通小时未设时兼容 ISSUE_SLA_DAYS；旧 ISSUE_SLA_TIME 只保留解析兼容，不再控制扫描。
def _parse_sla_days(raw: Optional[str]) -> int:
    try:
        days = int(raw) if raw is not None else 3
    except (TypeError, ValueError):
        return 3
    return days if days >= 1 else 3


def _parse_hhmm(raw: Optional[str], default: str = "18:10") -> str:
    if not raw:
        return default
    try:
        hour, minute = raw.split(":", 1)
        h, m = int(hour), int(minute)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except (TypeError, ValueError):
        pass
    return default


ISSUE_SLA_DAYS = _parse_sla_days(os.getenv("ISSUE_SLA_DAYS"))
def _parse_sla_hours(raw, default):
    try:
        hours=int(raw)
        return hours if 1<=hours<=87600 else default
    except (TypeError,ValueError):
        return default

ISSUE_SLA_NORMAL_HOURS = _parse_sla_hours(os.getenv('ISSUE_SLA_NORMAL_HOURS'),min(ISSUE_SLA_DAYS*24,87600))
ISSUE_SLA_ACCIDENT_HOURS = _parse_sla_hours(os.getenv('ISSUE_SLA_ACCIDENT_HOURS'),24)
ISSUE_SLA_QUALITY_HOURS = _parse_sla_hours(os.getenv('ISSUE_SLA_QUALITY_HOURS'),24)
ISSUE_SLA_TIME = _parse_hhmm(os.getenv("ISSUE_SLA_TIME"))
REPORT_WEEKLY_TIME = _parse_hhmm(os.getenv("REPORT_WEEKLY_TIME"), "20:00")  # 项目当地周日晚，HH:MM

# AI 项目整理助手（密钥仅服务端读取，不会返回浏览器）
AI_PROVIDER = os.getenv("AI_PROVIDER", "deepseek").strip().lower() or "deepseek"
AI_ALLOW_NO_KEY = os.getenv("AI_ALLOW_NO_KEY", "0") == "1"
try:
    AI_TIMEOUT_SECONDS = max(10, min(int(os.getenv("AI_TIMEOUT_SECONDS", "180")), 300))
except ValueError:
    AI_TIMEOUT_SECONDS = 180

# 文档收集箱：放入文件后自动触发 AI 归类（1=自动，0=手动）。

# AI 用量预算护栏（月度请求/token 上限，0=不限制；计数存 ai_usage_ledger 表）
def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


AI_MONTHLY_REQUESTS = _int_env("AGVPM_AI_MONTHLY_REQUESTS", 0)
AI_MONTHLY_TOKENS = _int_env("AGVPM_AI_MONTHLY_TOKENS", 0)


def _load_ai_api_key(env_name: str, file_env_name: str, fallback: bool = False) -> str:
    key_file = os.getenv(file_env_name, "").strip()
    if key_file:
        try:
            return Path(key_file).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    if fallback:
        generic_file = os.getenv("AI_API_KEY_FILE", "").strip()
        if generic_file:
            try:
                return Path(generic_file).read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return os.getenv("AI_API_KEY", "").strip()
    return ""


_AI_PRESETS = {    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "base_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "key_env": "DEEPSEEK_API_KEY",
        "key_file_env": "DEEPSEEK_API_KEY_FILE",
    },
    "mimo": {
        "name": "小米 MiMo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
        "base_env": "MIMO_BASE_URL",
        "model_env": "MIMO_MODEL",
        "key_env": "MIMO_API_KEY",
        "key_file_env": "MIMO_API_KEY_FILE",
    },
    "minimax": {
        "name": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M2.7",
        "base_env": "MINIMAX_BASE_URL",
        "model_env": "MINIMAX_MODEL",
        "key_env": "MINIMAX_API_KEY",
        "key_file_env": "MINIMAX_API_KEY_FILE",
    },
}


def _build_ai_providers() -> dict[str, dict[str, object]]:
    providers: dict[str, dict[str, object]] = {}
    for provider_id, preset in _AI_PRESETS.items():
        providers[provider_id] = {
            "id": provider_id,
            "name": preset["name"],
            "base_url": os.getenv(preset["base_env"], preset["base_url"]).strip().rstrip("/"),
            "model": os.getenv(preset["model_env"], preset["model"]).strip(),
            "api_key": _load_ai_api_key(
                preset["key_env"], preset["key_file_env"], fallback=provider_id == AI_PROVIDER,
            ),
            "allow_no_key": False,
        }
    providers["custom"] = {
        "id": "custom",
        "name": os.getenv("AI_PROVIDER_NAME", "自建兼容服务").strip() or "自建兼容服务",
        "base_url": os.getenv("AI_BASE_URL", "").strip().rstrip("/"),
        "model": os.getenv("AI_MODEL", "").strip(),
        "api_key": _load_ai_api_key("AI_API_KEY", "AI_API_KEY_FILE"),
        "allow_no_key": AI_ALLOW_NO_KEY,
    }
    return providers


AI_PROVIDERS = _build_ai_providers()
if AI_PROVIDER not in AI_PROVIDERS:
    AI_PROVIDER = "custom"

# ===== 消息通知外部渠道（钉钉机器人 / 通用 JSON webhook） =====
# 站内通知始终保留；外部外发走 notification_outbox 出站队列，由独立 scheduler 进程
# 按批投递（HYPE-58）。密钥只从环境变量或文件读取，绝不写死。
# NOTIFY_CHANNELS 支持逗号分隔：dingtalk（钉钉机器人）/ json（通用 JSON webhook）。
NOTIFY_CHANNELS = [
    channel.strip().lower()
    for channel in os.getenv("NOTIFY_CHANNELS", "").split(",")
    if channel.strip().lower()
]


def _load_notify_secret(env_name: str, file_env_name: str) -> str:
    """按 AI key 同样的模式读取 webhook 密钥：env 优先，文件路径兜底。"""
    key_file = os.getenv(file_env_name, "").strip()
    if key_file:
        try:
            return Path(key_file).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return os.getenv(env_name, "").strip()


DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
DINGTALK_WEBHOOK_SECRET = _load_notify_secret("DINGTALK_WEBHOOK_SECRET", "DINGTALK_WEBHOOK_SECRET_FILE")
# 通用 JSON webhook：可对接任意 HTTP 接收端（如企业微信群机器人 / 自建转发服务）。
# 密钥以 Authorization: Bearer <token> 头发送，同样只从环境变量或文件读取。
JSON_WEBHOOK_URL = os.getenv("JSON_WEBHOOK_URL", "").strip()
JSON_WEBHOOK_TOKEN = _load_notify_secret("JSON_WEBHOOK_TOKEN", "JSON_WEBHOOK_TOKEN_FILE")
# 外发超时（秒）：失败不影响站内通知
NOTIFY_TIMEOUT_SECONDS = float(os.getenv("NOTIFY_TIMEOUT_SECONDS", "3"))
# 出站队列投递参数：最大尝试次数 / 退避基数（attempts² × 基数秒）/ 每批条数
NOTIFY_RETRY_MAX_ATTEMPTS = int(os.getenv("NOTIFY_RETRY_MAX_ATTEMPTS", "3"))
NOTIFY_RETRY_BASE_SECONDS = float(os.getenv("NOTIFY_RETRY_BASE_SECONDS", "60"))
NOTIFY_DELIVERY_BATCH_SIZE = int(os.getenv("NOTIFY_DELIVERY_BATCH_SIZE", "50"))
