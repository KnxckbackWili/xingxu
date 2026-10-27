"""外部通知渠道适配器（HYPE-58：outbox + 独立 scheduler 投递）。

站内通知之外，可配置一个或多个外部渠道（钉钉机器人 / 通用 JSON webhook）做消息外发。
设计约束：
  - notify() 事务内只写站内通知 + notification_outbox 队列行，绝不发起外部 HTTP。
  - 外发由独立 scheduler 进程 deliver_outbox 按批投递：超时/限次重试/指数退避/幂等键/
    失败状态；任何外发失败都不回滚主业务、不重复站内通知。
  - 密钥/URL 只从环境变量或文件读取（见 app/config.py）；日志只打印 host，绝不打印
    query（access_token/签名）或密钥。
  - 未配置任何渠道时，notify() 直接把队列行标记 disabled，不积压。

接入说明见 docs/notifications.md。
"""

import hmac
import hashlib
import base64
import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import timedelta
from typing import Optional

from app import config
from app.time_utils import utcnow

logger = logging.getLogger(__name__)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """外部通知一律不跟随 3xx：任何重定向都视为发送失败（防 SSRF/开放跳转利用）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urlopen(request, timeout):
    """统一外发入口：显式 no-redirect opener；错误信息不含 URL query/Location。"""
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


# ===== 渠道启用判定 =====


def dingtalk_webhook_enabled() -> bool:
    """钉钉渠道是否可用的判定：渠道被启用 且 配置了 webhook URL。"""
    return "dingtalk" in config.NOTIFY_CHANNELS and bool(config.DINGTALK_WEBHOOK_URL)


def resolve_dingtalk_delivery(db=None) -> dict:
    """投递路径的钉钉配置解析：env 优先，其次管理员 DB 配置（每次投递动态读取，保存即生效）。

    返回 {enabled, webhook_url, secret}；与 channel_settings.resolve_dingtalk 等价，
    这里做一层惰性导入避免循环依赖。
    """
    from app.services.channel_settings import resolve_dingtalk

    cfg = resolve_dingtalk(db)
    return {
        "enabled": bool(cfg["enabled"] and cfg["webhook_url"]),
        "webhook_url": cfg["webhook_url"],
        "secret": cfg["secret"],
        "source": cfg["source"],
    }


def json_webhook_enabled() -> bool:
    """通用 JSON webhook 渠道是否可用。"""
    return "json" in config.NOTIFY_CHANNELS and bool(config.JSON_WEBHOOK_URL)


def channels_enabled() -> bool:
    """是否至少有一个可投递的外部渠道（含 URL）。"""
    return dingtalk_webhook_enabled() or json_webhook_enabled()


def channels_enabled_db(db=None) -> bool:
    """env 或 DB 配置任一可用即视为启用（notify() 落队列状态用）。"""
    if channels_enabled():
        return True
    if db is None:
        return False
    return resolve_dingtalk_delivery(db)["enabled"]


def _mask_url(url: str) -> str:
    """日志安全：只保留 scheme://host/path，绝不打印 query（access_token/签名等）。"""
    try:
        parsed = urllib.parse.urlsplit(url)
        if not parsed.scheme:
            return "<webhook-url>"
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:  # noqa: BLE001 - 打日志必须兜底
        return "<webhook-url>"


# ===== 钉钉机器人 =====


def dingtalk_sign(secret: str, timestamp_ms: int) -> str:
    """钉钉机器人加签：HMAC-SHA256(secret, timestamp + '\\n' + secret) → base64 → URL 编码。

    secret 为空时不签名（未加签的机器人直接外发）。
    """
    if not secret:
        return ""
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


def _dingtalk_payload(title: str, content: str, ntype: str) -> dict:
    """把站内通知转成钉钉 markdown 消息。内容超长时截断，避免被机器人限长拒绝。"""
    text = f"### {title}\n\n{content or '（无详情）'}"
    if ntype:
        text += f"\n\n> 类型：{ntype}"
    return {
        "msgtype": "markdown",
        "markdown": {"title": (title or "行序通知")[:20], "text": text[:4000]},
    }


def send_dingtalk_with(
    url: str,
    secret: str = "",
    title: str = "",
    content: str = "",
    ntype: str = "system",
    idempotency_key: str = "",
) -> bool:
    """使用显式 URL/Secret 发送（管理员测试通知与投递路径共用）；任何异常都吞掉并返回 False。

    每次实际发送前重新解析并校验官方主机与全部解析 IP（SSRF 防线）；
    加签用结构化 query 重建，access_token/timestamp/sign 各恰好一次；
    3xx 重定向一律判失败；错误详情/日志绝不回显 Location、token 或 Secret。
    """
    if not url:
        return False
    from app.services import channel_settings  # 惰性导入避免循环依赖

    try:
        channel_settings.assert_official_endpoint(url)
    except ValueError as error:
        logger.warning("钉钉通知发送前校验失败（%s）：%s", _mask_url(url), error)
        return False
    if secret:
        url = channel_settings.build_signed_dingtalk_url(url, secret)
    body = _dingtalk_payload(title, content, ntype)
    headers = {"Content-Type": "application/json"}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with _urlopen(request, timeout=config.NOTIFY_TIMEOUT_SECONDS) as response:
            result = response.read(512).decode("utf-8", errors="replace")
        if '"errcode":0' in result or '"errcode": 0' in result:
            return True
        # Provider error bodies can echo a credential-bearing URL. Log only the
        # result category, never an untrusted response body.
        logger.warning("钉钉通知返回异常（%s）", _mask_url(url))
        return False
    except (urllib.error.URLError, OSError, ValueError) as error:
        logger.warning(
            "钉钉通知发送失败（%s）：%s", _mask_url(url), type(error).__name__
        )
        return False


def _send_dingtalk(
    title: str,
    content: str,
    ntype: str,
    idempotency_key: str = "",
    url: str = "",
    secret: str = "",
) -> bool:
    """兼容入口：未显式给 URL 时回退到部署环境变量（旧测试/脚本路径）。"""
    url = url or config.DINGTALK_WEBHOOK_URL
    secret = secret if secret else config.DINGTALK_WEBHOOK_SECRET
    return send_dingtalk_with(url, secret, title, content, ntype, idempotency_key)


# ===== 通用 JSON webhook =====


def _json_payload(
    title: str,
    content: str,
    ntype: str,
    project_id: Optional[str],
    idempotency_key: str,
) -> dict:
    """通用 JSON 负载：结构化字段 + 幂等键，接收方可按 idempotency_key 去重。"""
    return {
        "title": title or "行序通知",
        "content": content or "",
        "type": ntype or "system",
        "project_id": project_id,
        "occurred_at": utcnow().isoformat(),
        "idempotency_key": idempotency_key,
        "source": "agv-pm",
    }


def _send_json_webhook(
    title: str,
    content: str,
    ntype: str,
    project_id: Optional[str],
    idempotency_key: str = "",
) -> bool:
    """同步发送一条通用 JSON webhook；任何异常都吞掉并返回 False。"""
    url = config.JSON_WEBHOOK_URL
    if not url:
        return False
    headers = {"Content-Type": "application/json"}
    token = getattr(config, "JSON_WEBHOOK_TOKEN", "") or ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    data = json.dumps(
        _json_payload(title, content, ntype, project_id, idempotency_key),
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with _urlopen(request, timeout=config.NOTIFY_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            response.read(512)
        if 200 <= status < 300:
            return True
        logger.warning("JSON 通知返回状态异常（%s）：HTTP %s", _mask_url(url), status)
        return False
    except (urllib.error.URLError, OSError, ValueError) as error:
        logger.warning(
            "JSON 通知发送失败（%s）：%s", _mask_url(url), type(error).__name__
        )
        return False


# ===== 出站队列投递 =====


def _deliver_one(db, row) -> bool:
    """投递到全部已启用渠道。任一渠道成功即视为已送达（消息已发出）。"""
    delivered = False
    dingtalk = resolve_dingtalk_delivery(db)
    if dingtalk["enabled"]:
        delivered = (
            send_dingtalk_with(
                dingtalk["webhook_url"],
                dingtalk["secret"],
                row.title,
                row.content,
                row.ntype,
                row.idempotency_key,
            )
            or delivered
        )
    if json_webhook_enabled():
        delivered = (
            _send_json_webhook(
                row.title, row.content, row.ntype, row.project_id, row.idempotency_key
            )
            or delivered
        )
    return delivered


def deliver_outbox(db, batch_size: Optional[int] = None, now=None) -> dict:
    """按批投递到期的出站通知（由独立 scheduler 进程每分钟调用）。

    状态机：pending → delivering → delivered / failed(→重试) / dead(超限) / disabled(无渠道)。
    退避：attempts² × NOTIFY_RETRY_BASE_SECONDS（1 次后 1min，2 次后 4min，3 次后 9min…）。
    """
    from app.models import NotificationOutbox, Project

    now = now or utcnow()
    batch_size = batch_size or getattr(config, "NOTIFY_DELIVERY_BATCH_SIZE", 50)
    rows = (
        db.query(NotificationOutbox)
        .filter(
            NotificationOutbox.status.in_(["pending", "failed"]),
            NotificationOutbox.next_retry_at.is_(None)
            | (NotificationOutbox.next_retry_at <= now),
        )
        .order_by(NotificationOutbox.created_at.asc())
        .limit(batch_size)
        .all()
    )
    if not rows:
        return {"processed": 0, "delivered": 0, "failed": 0, "dead": 0, "disabled": 0}
    if not channels_enabled_db(db):
        for row in rows:
            row.status = "disabled"
            row.updated_at = now
        db.commit()
        return {
            "processed": len(rows),
            "delivered": 0,
            "failed": 0,
            "dead": 0,
            "disabled": len(rows),
        }
    delivered = failed = dead = disabled = 0
    for row in rows:
        project = db.get(Project, row.project_id) if row.project_id else None
        row.status = "delivering"
        row.attempts = (row.attempts or 0) + 1
        db.flush()
        try:
            ok = _deliver_one(db, row)
        except Exception as error:
            logger.warning("通知投递异常（%s）：%s", row.id, type(error).__name__)
            ok = False
        if ok:
            row.status = "delivered"
            row.last_error = ""
            delivered += 1
        else:
            max_attempts = row.max_attempts or getattr(
                config, "NOTIFY_RETRY_MAX_ATTEMPTS", 3
            )
            if row.attempts >= max_attempts:
                row.status = "dead"
                dead += 1
            else:
                row.status = "failed"
                backoff = row.attempts**2 * getattr(
                    config, "NOTIFY_RETRY_BASE_SECONDS", 60
                )
                row.next_retry_at = now + timedelta(seconds=backoff)
                failed += 1
        row.updated_at = now
    db.commit()
    return {
        "processed": len(rows),
        "delivered": delivered,
        "failed": failed,
        "dead": dead,
        "disabled": disabled,
    }


# ===== 兼容：直接外发（测试/脚本用；业务入口一律走 outbox） =====


def send_to_channels(
    title: str,
    content: str = "",
    ntype: str = "system",
    project_id: Optional[str] = None,
    idempotency_key: str = "",
    db=None,
) -> bool:
    """同步投递到全部已启用渠道并返回是否至少成功一次（HYPE-58 后仅供测试/脚本）。"""
    delivered = False
    dingtalk = resolve_dingtalk_delivery(db)
    if dingtalk["enabled"]:
        overrides = (
            {"url": dingtalk["webhook_url"], "secret": dingtalk["secret"]}
            if dingtalk["source"] == "db"
            else {}
        )
        delivered = (
            _send_dingtalk(title, content, ntype, idempotency_key, **overrides)
            or delivered
        )
    if json_webhook_enabled():
        delivered = (
            _send_json_webhook(title, content, ntype, project_id, idempotency_key)
            or delivered
        )
    return delivered
