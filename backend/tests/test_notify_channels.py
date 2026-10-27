"""HYPE-58：外部通知渠道适配器测试（outbox 投递/重试/退避/幂等/JSON 适配器）。"""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta

import pytest

from app import config
from app.services.notify_channels import (
    _dingtalk_payload,
    _json_payload,
    _mask_url,
    _send_dingtalk,
    _send_json_webhook,
    channels_enabled,
    deliver_outbox,
    dingtalk_sign,
    dingtalk_webhook_enabled,
    json_webhook_enabled,
    send_to_channels,
)


class FakeResponse:
    """urllib.request.urlopen 的桩：200 状态 + 钉钉 errcode=0 响应体。"""

    status = 200

    def __init__(self, body: bytes = b'{"errcode":0}'):
        self._body = body

    def read(self, *args, **kwargs):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _enable_dingtalk(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", ["dingtalk"])
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send?access_token=secret-token")
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_SECRET", "")


def _enable_json(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", ["dingtalk", "json"])
    monkeypatch.setattr(config, "JSON_WEBHOOK_URL", "https://hooks.example.com/agv?channel=team")
    monkeypatch.setattr(config, "JSON_WEBHOOK_TOKEN", "tok-secret")


def _patch_urlopen(monkeypatch, fake):
    """拦截统一外发入口 _urlopen（no-redirect opener），不触网。"""
    import app.services.notify_channels as notify_channels
    monkeypatch.setattr(notify_channels, "_urlopen", fake)


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch):
    """发送前会重新解析官方主机并校验 IP；单测统一 stub 成公网 IP，避免真实 DNS。"""
    import socket
    from app.services import channel_settings
    monkeypatch.setattr(channel_settings.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


def _header(request, name: str):
    """urllib 把 header 名 capitalize 归一化（X-Idempotency-Key → X-idempotency-key），
    get_header 在新版本 Python 是精确键匹配——这里统一大小写不敏感取值。"""
    target = name.lower()
    for key, value in request.header_items():
        if key.lower() == target:
            return value
    return None


# ===== 加签 / 启用判定 / 负载 =====

def test_dingtalk_sign_matches_documented_algorithm():
    """加签 = HMAC-SHA256(secret, timestamp + '\\n' + secret) → base64 → URL 编码。"""
    secret = "SEC0123456789abcdef"
    timestamp_ms = 1617615341000
    expected = base64.b64encode(
        hmac.new(secret.encode(), f"{timestamp_ms}\n{secret}".encode(), hashlib.sha256).digest(),
    ).decode()
    import urllib.parse
    expected = urllib.parse.quote_plus(expected)

    assert dingtalk_sign(secret, timestamp_ms) == expected
    # 空密钥不签名（未加签机器人）
    assert dingtalk_sign("", timestamp_ms) == ""


def test_dingtalk_webhook_enabled(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", ["dingtalk"])
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send?access_token=x")
    assert dingtalk_webhook_enabled() is True

    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "")
    assert dingtalk_webhook_enabled() is False

    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send?access_token=x")
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", [])
    assert dingtalk_webhook_enabled() is False


def test_json_webhook_enabled_and_channels_enabled(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", [])
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "JSON_WEBHOOK_URL", "")
    assert json_webhook_enabled() is False
    assert channels_enabled() is False

    # 只有 json 渠道且配置了 URL → 启用
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", ["json"])
    monkeypatch.setattr(config, "JSON_WEBHOOK_URL", "https://hooks.example.com/hook")
    assert json_webhook_enabled() is True
    assert channels_enabled() is True

    # 渠道在列表但没 URL → 不启用
    monkeypatch.setattr(config, "JSON_WEBHOOK_URL", "")
    assert json_webhook_enabled() is False
    assert channels_enabled() is False


def test_dingtalk_payload_is_markdown():
    payload = _dingtalk_payload("任务逾期", "项目 A 有 3 个任务逾期", "system")
    assert payload["msgtype"] == "markdown"
    md = payload["markdown"]
    assert md["title"] == "任务逾期"
    assert "任务逾期" in md["text"]
    assert "项目 A 有 3 个任务逾期" in md["text"]
    assert "system" in md["text"]

    # 长内容截断，避免机器人限长拒绝
    long_payload = _dingtalk_payload("标题", "x" * 10000, "")
    assert len(long_payload["markdown"]["text"]) <= 4000


def test_json_payload_shape_and_idempotency_key():
    payload = _json_payload("问题已上报", "详情", "issue_reported", "p1", "idem-123")
    assert payload["title"] == "问题已上报"
    assert payload["type"] == "issue_reported"
    assert payload["project_id"] == "p1"
    assert payload["idempotency_key"] == "idem-123"
    assert payload["source"] == "agv-pm"
    assert "occurred_at" in payload

    # 空字段兜底
    empty = _json_payload("", "", "", None, "idem-456")
    assert empty["title"] == "行序通知"
    assert empty["type"] == "system"
    assert empty["project_id"] is None


def test_mask_url_strips_query_and_secret():
    url = "https://oapi.dingtalk.com/robot/send?access_token=supersecret&timestamp=123&sign=xyz"
    masked = _mask_url(url)
    assert masked == "https://oapi.dingtalk.com/robot/send"
    assert "supersecret" not in masked
    assert "xyz" not in masked

    broken = _mask_url("not a url")
    assert broken == "<webhook-url>"


# ===== 发送（失败吞掉 / JSON 鉴权头） =====

def test_send_dingtalk_failure_is_swallowed(monkeypatch):
    _enable_dingtalk(monkeypatch)

    def fake_urlopen(request, timeout=None):
        raise OSError("network unreachable")

    _patch_urlopen(monkeypatch, fake_urlopen)
    # 失败只返回 False，绝不抛异常
    assert _send_dingtalk("标题", "内容", "system") is False


def test_send_json_webhook_success_sends_token_and_body(monkeypatch):
    _enable_json(monkeypatch)
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["auth"] = _header(request, "Authorization")
        captured["idem"] = _header(request, "X-Idempotency-Key")
        return FakeResponse()

    _patch_urlopen(monkeypatch, fake_urlopen)
    assert _send_json_webhook("标题", "内容", "system", "p1", "idem-999") is True
    assert captured["auth"] == "Bearer tok-secret"
    assert captured["idem"] == "idem-999"
    import json
    body = json.loads(captured["body"].decode("utf-8"))
    assert body["title"] == "标题"
    assert body["project_id"] == "p1"
    assert body["idempotency_key"] == "idem-999"


def test_send_json_webhook_non_2xx_is_failure(monkeypatch):
    _enable_json(monkeypatch)

    class ErrorResponse(FakeResponse):
        status = 500

    _patch_urlopen(monkeypatch, lambda request, timeout=None: ErrorResponse())
    assert _send_json_webhook("标题", "内容", "system", None) is False


def test_send_to_channels_noop_without_config(monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", [])
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "JSON_WEBHOOK_URL", "")
    assert send_to_channels("标题", "内容") is False


def test_send_to_channels_forwards_to_all_enabled(monkeypatch):
    _enable_dingtalk(monkeypatch)
    _enable_json(monkeypatch)

    import app.services.notify_channels as notify_channels
    calls: list[str] = []

    def fake_ding(title, content, ntype, idem=""):
        calls.append("dingtalk")
        return True

    def fake_json(title, content, ntype, project_id, idem=""):
        calls.append("json")
        return True

    monkeypatch.setattr(notify_channels, "_send_dingtalk", fake_ding)
    monkeypatch.setattr(notify_channels, "_send_json_webhook", fake_json)
    assert send_to_channels("标题", "内容", "system", "p1", "idem-1") is True
    assert calls == ["dingtalk", "json"]


# ===== notify() 落库（站内通知 + 出站队列，绝不外发） =====

def _admin_id():
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        return db.query(User).filter_by(username="admin").first().id


def test_notify_creates_inapp_and_outbox_row_no_http(client, monkeypatch):
    """HYPE-58：notify() 只在事务内写站内通知 + outbox 行，绝不发起外部 HTTP。"""
    import app.services.notify_channels as notify_channels

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("notify() 内不应发起外部 HTTP 请求")

    _patch_urlopen(monkeypatch, fail_urlopen)
    _enable_dingtalk(monkeypatch)

    from app.db import SessionLocal
    from app.models import Notification, NotificationOutbox
    from app.services.notify import notify

    with SessionLocal() as db:
        admin = _admin_id()
        notify(db, admin, "问题已上报", "详情", ntype="issue_reported", project_id="p1")
        db.commit()

        notif = db.query(Notification).filter_by(user_id=admin).order_by(Notification.id.desc()).first()
        assert notif is not None
        assert notif.title == "问题已上报"
        assert notif.ntype == "issue_reported"

        outbox = db.query(NotificationOutbox).filter_by(notification_id=notif.id).first()
        assert outbox is not None
        assert outbox.status == "pending"  # 渠道已配置 → 等待投递
        assert outbox.idempotency_key          # 幂等键已生成
        assert outbox.max_attempts == getattr(config, "NOTIFY_RETRY_MAX_ATTEMPTS", 3)


def test_notify_marks_outbox_disabled_when_no_channels(client, monkeypatch):
    """未配置任何外部渠道 → outbox 直接 disabled，不积压。"""
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", [])
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "JSON_WEBHOOK_URL", "")

    from app.db import SessionLocal
    from app.models import Notification, NotificationOutbox
    from app.services.notify import notify

    with SessionLocal() as db:
        admin = _admin_id()
        notify(db, admin, "无渠道通知", "内容")
        db.commit()
        outbox = db.query(NotificationOutbox).filter_by(user_id=admin).order_by(NotificationOutbox.id.desc()).first()
        assert outbox is not None
        assert outbox.status == "disabled"
        # 站内通知不受影响
        assert db.query(Notification).filter_by(user_id=admin, title="无渠道通知").count() == 1


# ===== deliver_outbox 投递状态机 =====

def test_deliver_outbox_delivers_pending_rows(client, monkeypatch):
    """配置渠道 + 接收端正常 → pending → delivered，并带幂等键。"""
    _enable_dingtalk(monkeypatch)
    _enable_json(monkeypatch)
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured.setdefault("requests", []).append({
            "url": request.full_url,
            "idem": _header(request, "X-Idempotency-Key"),
        })
        return FakeResponse()

    _patch_urlopen(monkeypatch, fake_urlopen)

    from app.db import SessionLocal
    from app.models import NotificationOutbox
    from app.services.notify import notify

    with SessionLocal() as db:
        admin = _admin_id()
        notify(db, admin, "待投递", "内容", ntype="system", project_id="p1")
        db.commit()
        row = db.query(NotificationOutbox).filter_by(user_id=admin).order_by(NotificationOutbox.id.desc()).first()
        assert row.status == "pending"
        row_idem = row.idempotency_key

        stats = deliver_outbox(db)
        db.commit()
        assert stats["processed"] == 1
        assert stats["delivered"] == 1

        db.refresh(row)
        assert row.status == "delivered"
        assert row.attempts == 1

    # 两个渠道都收到且带同一幂等键
    assert len(captured["requests"]) == 2
    idems = {r["idem"] for r in captured["requests"]}
    assert len(idems) == 1
    assert row_idem in idems


def test_deliver_outbox_failure_retries_with_backoff_then_delivers(client, monkeypatch):
    """失败 → failed + next_retry_at 退避；到期后重试成功 → delivered。"""
    _enable_dingtalk(monkeypatch)
    from datetime import datetime

    def flaky_urlopen(request, timeout=None):
        if getattr(flaky_urlopen, "failing", True):
            flaky_urlopen.failing = False
            raise OSError("timeout")
        return FakeResponse()

    _patch_urlopen(monkeypatch, flaky_urlopen)

    from app.db import SessionLocal
    from app.models import NotificationOutbox
    from app.services.notify import notify

    with SessionLocal() as db:
        admin = _admin_id()
        notify(db, admin, "重试通知", "内容")
        db.commit()
        row = db.query(NotificationOutbox).filter_by(user_id=admin).order_by(NotificationOutbox.id.desc()).first()

        now = datetime(2026, 8, 30, 10, 0, 0)
        stats = deliver_outbox(db, now=now)
        assert stats["failed"] == 1
        db.refresh(row)
        assert row.status == "failed"
        assert row.attempts == 1
        # 退避 = attempts² × NOTIFY_RETRY_BASE_SECONDS = 1²×60s
        expected_retry = now + timedelta(seconds=getattr(config, "NOTIFY_RETRY_BASE_SECONDS", 60))
        assert row.next_retry_at == expected_retry

        # 未到期重试 → 本轮跳过（不重复投递）
        stats2 = deliver_outbox(db, now=now + timedelta(seconds=10))
        assert stats2["processed"] == 0

        # 到期后重试 → 成功
        stats3 = deliver_outbox(db, now=now + timedelta(seconds=61))
        assert stats3["delivered"] == 1
        db.refresh(row)
        assert row.status == "delivered"
        assert row.attempts == 2


def test_deliver_outbox_marks_dead_after_max_attempts(client, monkeypatch):
    """连续失败超过 max_attempts → dead，不再重试。"""
    _enable_dingtalk(monkeypatch)

    def always_fail(request, timeout=None):
        raise OSError("network down")

    _patch_urlopen(monkeypatch, always_fail)

    from app.db import SessionLocal
    from app.models import NotificationOutbox
    from app.services.notify import notify

    with SessionLocal() as db:
        admin = _admin_id()
        notify(db, admin, "终态通知", "内容")
        db.commit()
        row = db.query(NotificationOutbox).filter_by(user_id=admin).order_by(NotificationOutbox.id.desc()).first()
        assert row.max_attempts == 3

        now = datetime(2026, 8, 30, 10, 0, 0)
        # 第 1、2 次失败 → failed；第 3 次失败 → dead
        deliver_outbox(db, now=now)
        deliver_outbox(db, now=now + timedelta(minutes=10))
        stats = deliver_outbox(db, now=now + timedelta(minutes=40))
        assert stats["dead"] == 1
        db.refresh(row)
        assert row.status == "dead"
        assert row.attempts == 3

        # dead 不再进入投递批次
        assert deliver_outbox(db, now=now + timedelta(hours=1))["processed"] == 0


def test_deliver_outbox_disables_stale_pending_when_no_channels(client, monkeypatch):
    """渠道被关闭后，存量 pending 由投递兜底转 disabled。"""
    _enable_dingtalk(monkeypatch)

    from app.db import SessionLocal
    from app.models import NotificationOutbox
    from app.services.notify import notify

    with SessionLocal() as db:
        admin = _admin_id()
        notify(db, admin, "存量通知", "内容")
        db.commit()
        assert db.query(NotificationOutbox).filter_by(user_id=admin, status="pending").count() == 1

        # 渠道关闭
        monkeypatch.setattr(config, "NOTIFY_CHANNELS", [])
        monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "")
        monkeypatch.setattr(config, "JSON_WEBHOOK_URL", "")
        stats = deliver_outbox(db)
        assert stats["disabled"] == 1
        assert db.query(NotificationOutbox).filter_by(user_id=admin, status="disabled").count() == 1


def test_deliver_outbox_failure_never_crashes_or_duplicates_inapp(client, monkeypatch):
    """外发抛异常（含未知异常）不崩溃，站内通知不重复。"""
    _enable_dingtalk(monkeypatch)

    def boom(request, timeout=None):
        raise RuntimeError("channel crash")

    _patch_urlopen(monkeypatch, boom)

    from app.db import SessionLocal
    from app.models import Notification, NotificationOutbox
    from app.services.notify import notify

    with SessionLocal() as db:
        admin = _admin_id()
        notify(db, admin, "失败不动站内", "内容")
        db.commit()
        row = db.query(NotificationOutbox).filter_by(user_id=admin).order_by(NotificationOutbox.id.desc()).first()
        notif_id = row.notification_id

        stats = deliver_outbox(db)
        db.commit()
        assert stats["failed"] == 1
        # 站内通知仍恰有一条
        assert db.query(Notification).filter(Notification.id == notif_id).count() == 1
        # outbox 唯一（不会因失败重复生成）
        assert db.query(NotificationOutbox).filter(NotificationOutbox.notification_id == notif_id).count() == 1
