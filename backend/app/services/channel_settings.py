"""通知渠道管理员配置：解析优先级、SSRF 校验、掩码状态、保存与测试发送。

优先级：部署环境变量/env file（config 层已解析）> 数据库（notification_channel_configs）。
- env 已配置：渠道由部署托管，DB 配置被忽略，界面只读。
- DB 配置：Webhook/Secret 用 channel_crypto（Fernet/HKDF）加密存储；调度器每次投递动态读取，保存即生效。
- 任何返回值/日志都不得包含 Webhook query（access_token/签名）或 Secret 明文。
"""

import ipaddress
import socket
import urllib.parse
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.models import NotificationChannelConfig
from app.services.channel_crypto import encrypt_text, decrypt_text
from app.services.notify_channels import dingtalk_sign
from app.time_utils import utcnow

# 钉钉机器人官方主机与路径（严格白名单，防 SSRF）
DINGTALK_ALLOWED_HOST = "oapi.dingtalk.com"
DINGTALK_ALLOWED_PATH = "/robot/send"

_TEST_RATE_LIMIT = 5       # 测试发送：每用户每窗口次数
_TEST_RATE_WINDOW = 600.0  # 10 分钟


# ===== 渠道配置解析（投递/测试共用；env 优先） =====

def env_dingtalk_configured() -> bool:
    return bool(config.DINGTALK_WEBHOOK_URL)


def resolve_dingtalk(db: Optional[Session] = None) -> dict:
    """解析钉钉渠道当前生效配置（含明文 URL/Secret，仅供发送路径内部使用，禁止外泄）。

    返回 {source: 'env'|'db'|None, enabled, webhook_url, secret}。
    """
    if env_dingtalk_configured():
        return {
            "source": "env",
            "enabled": "dingtalk" in config.NOTIFY_CHANNELS,
            "webhook_url": config.DINGTALK_WEBHOOK_URL,
            "secret": config.DINGTALK_WEBHOOK_SECRET,
        }
    if db is not None:
        row = db.query(NotificationChannelConfig).filter_by(channel="dingtalk").first()
        if row and row.webhook_url_encrypted:
            try:
                url = decrypt_text(row.webhook_url_encrypted)
                secret = decrypt_text(row.secret_encrypted or "")
            except ValueError:
                return {"source": None, "enabled": False, "webhook_url": "", "secret": ""}
            # enabled=False（停用保留配置）时 URL 仍返回用于掩码展示，投递侧以 enabled 为准
            return {"source": "db", "enabled": bool(row.enabled and url),
                    "webhook_url": url, "secret": secret}
    return {"source": None, "enabled": False, "webhook_url": "", "secret": ""}


# ===== SSRF / 官方端点校验 =====

def validate_dingtalk_webhook(url: str) -> str:
    """严格校验钉钉机器人 Webhook：HTTPS + 官方主机/路径 + 拒绝内网解析。

    校验通过返回规整后的 URL；不合法抛 ValueError（detail 可直接展示）。
    """
    text = (url or "").strip()
    if not text:
        raise ValueError("Webhook 地址不能为空")
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme != "https":
        raise ValueError("Webhook 必须是 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("Webhook 不允许携带用户名/密码")
    if parsed.hostname != DINGTALK_ALLOWED_HOST:
        raise ValueError(f"Webhook 主机必须是官方地址 {DINGTALK_ALLOWED_HOST}")
    if parsed.port not in (None, 443):
        raise ValueError("Webhook 只允许默认 443 端口")
    if parsed.fragment:
        raise ValueError("Webhook 不允许携带 fragment")
    if parsed.path != DINGTALK_ALLOWED_PATH:  # 精确相等：/robot/sendX、/robot/send/ 均拒绝
        raise ValueError(f"Webhook 路径必须是 {DINGTALK_ALLOWED_PATH}")
    # 持久化 Webhook 只允许且必须恰好一个非空 access_token：
    # 拒绝 timestamp/sign（加签由系统在发送时重建）、重复参数、空值与一切未知参数。
    # parse_qsl 已做百分号解码：%61ccess_token 等编码绕过会还原成同名 key 参与判定。
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("Webhook 存在重复参数")
    if keys != ["access_token"]:
        raise ValueError("Webhook 必须且只能携带一个 access_token 参数（不接受 timestamp/sign/其他参数）")
    token = pairs[0][1]
    if not token.strip():
        raise ValueError("access_token 不能为空")
    # DNS 解析后拒绝内网/回环/链路本地/保留地址（防 DNS rebinding 的基础防线；
    # 实际请求阶段使用固定解析结果，不跟随跳转）
    try:
        infos = socket.getaddrinfo(parsed.hostname, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise ValueError("Webhook 主机无法解析") from error
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError("Webhook 不允许指向内网/保留地址")
    return text


def build_signed_dingtalk_url(url: str, secret: str) -> str:
    """发送时加签：结构化重建 query，保证 access_token/timestamp/sign 各恰好一次。

    输入 URL 已通过 validate_dingtalk_webhook（或为部署 env 托管的同构地址）；
    任何旧 timestamp/sign 一律丢弃，用新时间戳重签，防止签名重放参数注入。
    """
    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k == "access_token"]
    timestamp_ms = str(int(round(time.time() * 1000)))
    # dingtalk_sign is the legacy URL-encoded helper. urlencode below performs
    # the one and only query encoding, so first recover the raw base64 value.
    sign = urllib.parse.unquote_plus(dingtalk_sign(secret, int(timestamp_ms)))
    kept += [("timestamp", timestamp_ms), ("sign", sign)]
    query = urllib.parse.urlencode(kept)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def assert_official_endpoint(url: str) -> None:
    """每次实际发送前重新校验：官方主机/路径/query + DNS 解析 IP 全部合规（SSRF 防线）。

    校验失败抛 ValueError；错误信息为静态文案，绝不回显 URL/Location/token/Secret。
    """
    validate_dingtalk_webhook(url)

def mask_webhook(url: str) -> str:
    """掩码展示：保留 scheme://host/path，query 一律打码（access_token 是凭据）。"""
    parsed = urllib.parse.urlsplit(url or "")
    if not parsed.scheme:
        return ""
    mark = "?access_token=****" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}{mark}"


# ===== 管理员状态（安全视图：无任何明文凭据） =====

def get_status(db: Session) -> dict:
    """GET 响应：只有 configured/掩码/来源/最近测试结果，绝不含明文凭据。"""
    dingtalk = resolve_dingtalk(db)
    row = db.query(NotificationChannelConfig).filter_by(channel="dingtalk").first()
    env_managed = dingtalk["source"] == "env"
    return {
        "in_app": {"enabled": True, "label": "站内通知（始终开启）"},
        "dingtalk": {
            "configured": bool(dingtalk["webhook_url"]),
            "enabled": bool(dingtalk["enabled"]),
            "source": dingtalk["source"],  # env / db / None
            "env_managed": env_managed,
            "webhook_masked": mask_webhook(dingtalk["webhook_url"]),
            "secret_set": bool(
                config.DINGTALK_WEBHOOK_SECRET if env_managed
                else (row and row.secret_encrypted)
            ),
            "editable": not env_managed,
            "last_test": None if not row or not row.last_test_at else {
                "at": row.last_test_at.isoformat() if isinstance(row.last_test_at, datetime) else str(row.last_test_at),
                "success": bool(row.last_test_success),
                "detail": row.last_test_detail or "",
            },
        },
    }


# ===== 保存（管理员；env 托管时只读） =====

def save_dingtalk(db: Session, admin_user_id: str, *, enabled: bool,
                  webhook_url: Optional[str] = None,
                  secret: Optional[str] = None,
                  clear_secret: bool = False) -> dict:
    """保存钉钉 DB 配置。secret=None 保留现有；非空覆盖；clear_secret=True 显式清除。"""
    if env_dingtalk_configured():
        raise PermissionError("钉钉渠道由部署环境托管，请在部署环境变量中修改")

    # 先完成全部校验，再触碰数据库（非法输入不得留下任何行）
    url_to_save: Optional[str] = None
    if enabled:
        url_to_save = (webhook_url or "").strip()
        if not url_to_save:
            # 开启时必须已有可用 URL（表单里留空沿用旧值）
            existing = _existing_webhook_url(db)
            if not existing:
                raise ValueError("启用钉钉渠道前请先填写 Webhook 地址")
            url_to_save = existing
        validate_dingtalk_webhook(url_to_save)
    elif webhook_url is not None and webhook_url.strip():
        # 停用状态下也允许更新 URL（校验但不改变 enabled）
        url_to_save = webhook_url.strip()
        validate_dingtalk_webhook(url_to_save)

    row = _ensure_dingtalk_row(db)
    if url_to_save:
        row.webhook_url_encrypted = encrypt_text(url_to_save)
    if clear_secret:
        row.secret_encrypted = ""
    elif secret is not None and secret != "":
        row.secret_encrypted = encrypt_text(secret)

    row.enabled = bool(enabled)
    row.updated_by = admin_user_id
    db.commit()
    db.refresh(row)
    return {"enabled": row.enabled, "secret_set": bool(row.secret_encrypted)}


def _existing_webhook_url(db: Session) -> str:
    row = db.query(NotificationChannelConfig).filter_by(channel="dingtalk").one_or_none()
    if row is None or not row.webhook_url_encrypted:
        return ""
    try:
        return decrypt_text(row.webhook_url_encrypted)
    except ValueError:
        return ""


def disable_dingtalk(db: Session, admin_user_id: str) -> None:
    """停用渠道（保留配置，便于之后重新启用）。"""
    if env_dingtalk_configured():
        raise PermissionError("钉钉渠道由部署环境托管，请在部署环境变量中停用")
    row = db.query(NotificationChannelConfig).filter_by(channel="dingtalk").first()
    if row is not None:
        row.enabled = False
        row.updated_by = admin_user_id
        db.commit()


def _ensure_dingtalk_row(db: Session) -> NotificationChannelConfig:
    """并发安全的 get-or-create：唯一键冲突（IntegrityError）时 rollback+重读，
    两个并发 admin 首次保存也不会 500 / 出重复行 / 丢最终状态。"""
    def query_one():
        return db.query(NotificationChannelConfig).filter_by(channel="dingtalk").one_or_none()

    row = query_one()
    if row is not None:
        return row
    row = NotificationChannelConfig(channel="dingtalk")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    # 无论谁先插入成功，都以库内最新一行为准继续更新（最后提交者持有最终状态）
    return query_one()


# ===== 测试发送（管理员；限流 + 审计；不产生业务通知） =====

def record_test_result(db: Session, success: bool, detail: str) -> None:
    row = _ensure_dingtalk_row(db)
    row.last_test_at = utcnow()
    row.last_test_success = success
    row.last_test_detail = (detail or "")[:300]
    db.commit()


def send_test_dingtalk(db: Session, admin_user_id: str) -> dict:
    """发送一条测试消息到当前生效配置；直接同步发送（不走 outbox，避免重复业务通知）。"""
    from app.services import notify_channels

    cfg = resolve_dingtalk(db)
    if not cfg["webhook_url"]:
        return {"success": False, "detail": "钉钉渠道尚未配置 Webhook"}
    try:
        if cfg["source"] == "db":
            validate_dingtalk_webhook(cfg["webhook_url"])
    except ValueError as error:
        record_test_result(db, False, str(error))
        return {"success": False, "detail": str(error)}

    ok = notify_channels.send_dingtalk_with(
        cfg["webhook_url"], cfg["secret"],
        title="行序 · 测试通知",
        content="这是一条管理员发出的渠道测试消息，收到即表示钉钉渠道配置成功。",
        ntype="system",
    )
    detail = "发送成功" if ok else "发送失败（Webhook 返回异常或网络错误，详情见服务端日志）"
    record_test_result(db, ok, detail)
    return {"success": ok, "detail": detail}
