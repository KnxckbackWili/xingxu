"""通知渠道管理员配置：权限/优先级/掩码/SSRF/启停生效/Secret 保留与清除/测试发送。"""

import json
import uuid

import pytest

from app import config
from app.models import NotificationChannelConfig, NotificationOutbox
from app.services import channel_settings, notify_channels
from app.services.channel_crypto import decrypt_text

GOOD_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=test-token-123"


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch):
    """发送/保存校验会解析官方主机；单测统一 stub 成公网 IP，避免真实 DNS 依赖。"""
    import socket
    from app.services import channel_settings
    monkeypatch.setattr(channel_settings.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


# ===== 权限：非 admin 一律 403 =====

def test_channels_api_requires_admin(client, admin_headers, pm_headers, worker_headers):
    assert client.get("/api/notification-channels", headers=admin_headers).status_code == 200
    for headers in (pm_headers, worker_headers):
        assert client.get("/api/notification-channels", headers=headers).status_code == 403
        assert client.put("/api/notification-channels/dingtalk", headers=headers,
                          json={"enabled": True, "webhook_url": GOOD_WEBHOOK}).status_code == 403
        assert client.post("/api/notification-channels/dingtalk/test",
                           headers=headers).status_code == 403
        assert client.delete("/api/notification-channels/dingtalk", headers=headers).status_code == 403


# ===== 默认关闭 + 掩码状态 =====

def test_default_status_is_off_and_masked(client, admin_headers):
    r = client.get("/api/notification-channels", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["in_app"]["enabled"] is True
    ding = body["dingtalk"]
    assert ding["configured"] is False and ding["enabled"] is False
    assert ding["source"] is None and ding["secret_set"] is False


# ===== 保存/读取不泄密 =====

def test_save_and_status_never_leak_secrets(client, admin_headers):
    r = client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                   json={"enabled": True, "webhook_url": GOOD_WEBHOOK,
                         "secret": "SECRET-begin-XYZ"})
    assert r.status_code == 200 and r.json()["enabled"] is True
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        stored = db.query(NotificationChannelConfig).filter_by(channel="dingtalk").one()
        assert "test-token-123" not in (stored.webhook_url_encrypted or "")
        assert stored.secret_encrypted and "SECRET-begin-XYZ" not in stored.secret_encrypted
        assert decrypt_text(stored.webhook_url_encrypted) == GOOD_WEBHOOK
        assert decrypt_text(stored.secret_encrypted) == "SECRET-begin-XYZ"
    finally:
        db.close()
    body = client.get("/api/notification-channels", headers=admin_headers).json()["dingtalk"]
    text = json.dumps(body)
    assert "test-token-123" not in text and "SECRET-begin-XYZ" not in text
    assert body["configured"] is True and body["enabled"] is True
    assert body["source"] == "db" and body["secret_set"] is True
    assert body["webhook_masked"].startswith("https://oapi.dingtalk.com/robot/send")
    assert "****" in body["webhook_masked"]


# ===== env 优先：env 托管时 DB 修改被拒、状态只读 =====

def test_env_overrides_db(client, admin_headers, monkeypatch):
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_URL", "https://oapi.dingtalk.com/robot/send?access_token=env-token")
    monkeypatch.setattr(config, "DINGTALK_WEBHOOK_SECRET", "env-secret")
    monkeypatch.setattr(config, "NOTIFY_CHANNELS", "dingtalk")
    # 先存一条 DB 配置
    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": True, "webhook_url": GOOD_WEBHOOK,
                            "secret": "db-secret"}).status_code in (200, 409)
    body = client.get("/api/notification-channels", headers=admin_headers).json()["dingtalk"]
    assert body["source"] == "env" and body["env_managed"] is True
    assert body["configured"] is True and body["secret_set"] is True
    assert "env-token" not in json.dumps(body)
    # env 托管时 PUT/DELETE 拒绝（409），页面只读
    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": False}).status_code == 409
    assert client.delete("/api/notification-channels/dingtalk", headers=admin_headers).status_code == 409


# ===== SSRF / 官方端点校验 =====

@pytest.mark.parametrize("bad", [
    "http://oapi.dingtalk.com/robot/send?access_token=x",                     # 非 HTTPS
    "https://oapi.example.com/robot/send?access_token=x",                     # 非官方主机
    "https://oapi.dingtalk.com/other?access_token=x",                         # 非官方路径
    "https://127.0.0.1/robot/send?access_token=x",                            # 回环地址
    "https://192.168.1.1/robot/send?access_token=x",                          # 内网地址
    "https://user:pw@oapi.dingtalk.com/robot/send?access_token=x",            # URL 内嵌凭据
    "https://oapi.dingtalk.com/robot/send?access_token=x&callback=http://evil",  # 额外参数
    "https://oapi.dingtalk.com:8443/robot/send?access_token=x",               # 非默认端口
])
def test_webhook_validation_rejects(client, admin_headers, bad):
    r = client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                   json={"enabled": True, "webhook_url": bad})
    assert r.status_code == 400
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        assert db.query(NotificationChannelConfig).filter_by(channel="dingtalk").first() is None
    finally:
        db.close()


# ===== Secret 留空保留 / 显式清除 =====

def test_secret_keep_and_clear(client, admin_headers):
    put = lambda **kw: client.put("/api/notification-channels/dingtalk",
                                  headers=admin_headers, json=kw)
    assert put(enabled=True, webhook_url=GOOD_WEBHOOK, secret="s1").status_code == 200
    # 留空（缺省 secret=None）→ 保留
    assert put(enabled=True, webhook_url=GOOD_WEBHOOK).status_code == 200
    body = client.get("/api/notification-channels", headers=admin_headers).json()["dingtalk"]
    assert body["secret_set"] is True
    # 显式清除
    assert put(enabled=True, webhook_url=GOOD_WEBHOOK, clear_secret=True).status_code == 200
    body = client.get("/api/notification-channels", headers=admin_headers).json()["dingtalk"]
    assert body["secret_set"] is False


# ===== 启停后投递生效（调度器动态读取，无需重启） =====

def _outbox_row(db):
    row = NotificationOutbox(title="投递烟测", content="n", ntype="system",
                             idempotency_key=f"idem-{uuid.uuid4()}")
    db.add(row)
    db.commit()
    return row


def test_enable_disable_affects_delivery(client, admin_headers, monkeypatch):
    sent = []
    monkeypatch.setattr(notify_channels, "send_dingtalk_with",
                        lambda url, secret, *a, **k: sent.append((url, secret)) or True)
    from app.db import SessionLocal

    def deliver():
        db = SessionLocal()
        try:
            return notify_channels.deliver_outbox(db)
        finally:
            db.close()

    # 未配置 → 队列直接 disabled
    db = SessionLocal(); row = _outbox_row(db); db.close()
    assert deliver()["disabled"] == 1

    # 管理员保存并启用 → 投递成功（URL/Secret 来自 DB，解密后使用）
    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": True, "webhook_url": GOOD_WEBHOOK,
                            "secret": "sign-secret"}).status_code == 200
    db = SessionLocal()
    try:
        row = _outbox_row(db)
    finally:
        db.close()
    result = deliver()
    assert result["delivered"] == 1
    assert sent and sent[-1][0] == GOOD_WEBHOOK and sent[-1][1] == "sign-secret"

    # 停用（配置保留）→ 不再投递
    assert client.delete("/api/notification-channels/dingtalk", headers=admin_headers).status_code == 200
    body = client.get("/api/notification-channels", headers=admin_headers).json()["dingtalk"]
    assert body["enabled"] is False and body["configured"] is True
    db = SessionLocal()
    try:
        row = _outbox_row(db)
    finally:
        db.close()
    assert deliver()["disabled"] == 1
    assert len(sent) == 1


# ===== 测试发送：限流 + 审计 + 日志/响应不泄密 =====

def test_send_test_notification_flow(client, admin_headers, monkeypatch, caplog):
    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": True, "webhook_url": GOOD_WEBHOOK,
                            "secret": "sign-secret"}).status_code == 200
    calls = []
    monkeypatch.setattr(notify_channels, "send_dingtalk_with",
                        lambda url, secret, *a, **k: calls.append((url, secret)) or True)
    with caplog.at_level("WARNING"):
        r = client.post("/api/notification-channels/dingtalk/test", headers=admin_headers)
    assert r.status_code == 200 and r.json()["success"] is True
    assert calls and calls[0][0] == GOOD_WEBHOOK and calls[0][1] == "sign-secret"
    # 审计：最近测试结果已落库（掩码），响应只含 success/detail
    body = client.get("/api/notification-channels", headers=admin_headers).json()["dingtalk"]
    assert body["last_test"]["success"] is True
    assert "test-token-123" not in json.dumps(body) + caplog.text
    # 未配置 URL 时测试发送明确失败且不抛 500
    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": False, "clear_secret": True}).status_code == 200
    db = client  # noqa: F841
    from app.db import SessionLocal
    s = SessionLocal(); s.query(NotificationChannelConfig).delete(); s.commit(); s.close()
    r = client.post("/api/notification-channels/dingtalk/test", headers=admin_headers)
    assert r.status_code == 200 and r.json()["success"] is False


def test_send_test_rate_limited(client, admin_headers, monkeypatch):
    monkeypatch.setattr(notify_channels, "send_dingtalk_with",
                        lambda url, secret, *a, **k: True)
    from app.services.rate_limit import reset_rate_limits
    codes = [client.post("/api/notification-channels/dingtalk/test",
                         headers=admin_headers).status_code for _ in range(6)]
    reset_rate_limits()
    assert codes.count(200) >= 1 and 429 in codes


# ===== 一审返工：Webhook 持久化严格化（精确路径 / 恰好一个非空 access_token） =====

@pytest.mark.parametrize("bad", [
    "https://oapi.dingtalk.com/robot/sendX?access_token=x",            # startswith 绕过（精确相等才允许）
    "https://oapi.dingtalk.com/robot/send/?access_token=x",            # 尾斜杠
    "https://oapi.dingtalk.com/robot/send?access_token=a&access_token=b",  # 重复 access_token
    "https://oapi.dingtalk.com/robot/send?access_token=",               # 空 access_token
    "https://oapi.dingtalk.com/robot/send?access_token=a&timestamp=1&sign=s",  # 旧签名参数持久化
    "https://oapi.dingtalk.com/robot/send?access_token=a&channel=weapp",  # 未知参数
    "https://oapi.dingtalk.com/robot/send?%61ccess_token=a&access_token=b",  # 百分号编码重复
    "https://oapi.dingtalk.com/robot/send?ACCESS_TOKEN=x",             # 大小写变体（未知参数）
    "https://oapi.dingtalk.com/robot/send?access_token=x#frag",        # fragment
])
def test_webhook_persistence_strict_query_path(client, admin_headers, bad):
    r = client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                   json={"enabled": True, "webhook_url": bad})
    assert r.status_code == 400, bad
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        assert db.query(NotificationChannelConfig).filter_by(channel="dingtalk").first() is None
    finally:
        db.close()


def test_signed_url_has_exactly_one_of_each_param():
    from app.services.channel_settings import build_signed_dingtalk_url
    # 输入即使残留旧 timestamp/sign（env 托管的历史地址），重建后也各恰好一次
    url = "https://oapi.dingtalk.com/robot/send?access_token=abc&timestamp=1&sign=old"
    out = build_signed_dingtalk_url(url, "sec")
    import urllib.parse as up
    q = up.parse_qsl(up.urlsplit(out).query)
    keys = [k for k, _ in q]
    assert keys.count("access_token") == 1
    assert keys.count("timestamp") == 1 and keys.count("sign") == 1
    assert set(keys) == {"access_token", "timestamp", "sign"}
    assert dict(q)["access_token"] == "abc" and dict(q)["timestamp"] != "1"


# ===== 一审返工：发送路径禁止 3xx 跳转，重定向判失败且不泄密 =====

def test_redirect_is_never_followed(client, admin_headers, monkeypatch, caplog):
    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": True, "webhook_url": GOOD_WEBHOOK,
                            "secret": "sign-secret"}).status_code == 200
    import urllib.error
    from app.services import notify_channels

    # 301/302/307 均模拟 urllib 的行为：no-redirect handler 下抛 HTTPError（不跟随）
    def fake_urlopen_301(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 301, "Moved Permanently", {}, None)

    def fake_urlopen_302(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 302, "Found", {}, None)

    for fake in (fake_urlopen_301, fake_urlopen_302):
        monkeypatch.setattr(notify_channels, "_urlopen", fake)
        ok = notify_channels.send_dingtalk_with(
            GOOD_WEBHOOK, "sign-secret", title="t", content="c", ntype="system")
        assert ok is False
    # 错误日志不得回显 token / Secret / Location
    log_text = caplog.text
    assert "test-token-123" not in log_text and "sign-secret" not in log_text
    assert "Location" not in log_text and "access_token=" not in log_text


def test_no_redirect_handler_refuses_all_3xx():
    import urllib.request
    from app.services.notify_channels import _NoRedirectHandler
    handler = _NoRedirectHandler()
    for code in (301, 302, 303, 307, 308):
        assert handler.redirect_request(None, None, code, "", {}, "https://evil.example/x") is None


def test_send_error_detail_never_echoes_credentials(client, admin_headers, monkeypatch):
    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": True, "webhook_url": GOOD_WEBHOOK}).status_code == 200
    import urllib.error
    from app.services import notify_channels

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://oapi.dingtalk.com/robot/send?access_token=test-token-123&Location=leak",
            302, "Found", {}, None)

    monkeypatch.setattr(notify_channels, "_urlopen", fake_urlopen)
    r = client.post("/api/notification-channels/dingtalk/test", headers=admin_headers)
    assert r.status_code == 200
    text = json.dumps(r.json())
    assert r.json()["success"] is False
    assert "test-token-123" not in text and "Location" not in text and "302" not in text


# ===== 一审返工：并发首次保存不 500 / 不重复行 / 不丢最终状态 =====

def test_concurrent_first_save_no_duplicate_no_500(client, admin_headers):
    """两个并发 admin 首次保存：无 500、单行、最终状态为其中一次完整保存。"""
    import threading
    from app.db import SessionLocal
    from app.models import NotificationChannelConfig

    results = []
    barrier = threading.Barrier(2)

    def worker(url_suffix):
        try:
            # 先各自登录，再在栅栏后同时发起首次保存（最大化并发插入竞态窗口）
            r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            h = {"Authorization": "Bearer " + r.json()["access_token"]}
            barrier.wait(timeout=5)
            resp = client.put("/api/notification-channels/dingtalk", headers=h, json={
                "enabled": True,
                "webhook_url": f"https://oapi.dingtalk.com/robot/send?access_token=tok-{url_suffix}",
            })
            results.append(resp.status_code)
        except Exception as exc:  # noqa: BLE001
            results.append(f"EXC:{exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(code == 200 for code in results), results
    db = SessionLocal()
    try:
        rows = db.query(NotificationChannelConfig).filter_by(channel="dingtalk").all()
        assert len(rows) == 1
        assert rows[0].enabled is True
        # 最终状态 = 两次保存之一，完整可解密、无丢失
        from app.services.channel_crypto import decrypt_text
        url = decrypt_text(rows[0].webhook_url_encrypted)
        assert url in ("https://oapi.dingtalk.com/robot/send?access_token=tok-0",
                       "https://oapi.dingtalk.com/robot/send?access_token=tok-1")
    finally:
        db.close()
