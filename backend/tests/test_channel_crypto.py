"""channel_crypto（Fernet/HKDF）：随机性、篡改、跨进程/重启/备份同 key、异 key 安全失败。"""

import base64
import os
import subprocess
import sys

import pytest

from app import config
from app.services import channel_crypto


def test_random_tokens_roundtrip():
    import secrets
    for _ in range(20):
        token = secrets.token_urlsafe(secrets.randbelow(64) + 1)
        assert channel_crypto.decrypt_text(channel_crypto.encrypt_text(token)) == token
    # 中文/换行/超长也逐字还原
    for text in ["中文密文内容\n第二行", "a" * 10000]:
        assert channel_crypto.decrypt_text(channel_crypto.encrypt_text(text)) == text


def test_empty_string_stays_empty():
    assert channel_crypto.encrypt_text("") == ""
    assert channel_crypto.decrypt_text("") == ""


def test_tamper_detected_invalidtoken():
    token = channel_crypto.encrypt_text("webhook-secret-123")
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[-1] ^= 0xFF  # 篡改 tag 最后一位
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode()
    with pytest.raises(ValueError) as exc:
        channel_crypto.decrypt_text(tampered)
    assert isinstance(exc.value.__cause__, Exception)


def test_cross_process_and_restart_same_key_decrypts(tmp_path, monkeypatch):
    """同一 SECRET_KEY/secret.key：新进程（模拟重启/备份恢复）可解密。"""
    secret = "cross-process-secret-值"
    token = channel_crypto.encrypt_text(secret)

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "from app.services.channel_crypto import decrypt_text; "
        f"print(decrypt_text({token!r}))"
    )
    # 场景 1：相同 SECRET_KEY env（备份同 key）
    env = {**os.environ, "SECRET_KEY": config.SECRET_KEY, "PYTHONPATH": backend_dir}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == secret

    # 场景 2：无 env，从 DATA_DIR/secret.key 读取（重启/恢复备份路径）
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "secret.key").write_text(config.SECRET_KEY)
    env2 = {**os.environ, "DATA_DIR": str(data_dir), "PYTHONPATH": backend_dir}
    env2.pop("SECRET_KEY", None)
    out2 = subprocess.run([sys.executable, "-c", code], env=env2, capture_output=True, text=True)
    assert out2.returncode == 0 and out2.stdout.strip() == secret


def test_different_key_fails_safely(monkeypatch):
    token = channel_crypto.encrypt_text("secret-under-old-key")
    monkeypatch.setattr(config, "SECRET_KEY", "a-completely-different-key")
    with pytest.raises(ValueError):
        channel_crypto.decrypt_text(token)
    # 解密失败必须抛 ValueError（包装 InvalidToken），绝不返回部分明文
    with pytest.raises(ValueError) as exc:
        channel_crypto.decrypt_text(token)
    assert "secret-under-old-key" not in str(exc.value)


def test_undecryptable_row_does_not_break_delivery_batch(client, admin_headers, monkeypatch):
    """异 key 密文行：解析降级为未配置，调度批次安全走 disabled，不抛异常。"""
    from app.db import SessionLocal
    from app.models import NotificationChannelConfig, NotificationOutbox
    from app.services import channel_settings, notify_channels
    import socket
    import uuid

    # Channel validation resolves DNS; keep this crypto regression independent
    # of external DNS just like the notification-channel tests.
    monkeypatch.setattr(
        channel_settings.socket, "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    assert client.put("/api/notification-channels/dingtalk", headers=admin_headers,
                      json={"enabled": True, "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=t"}).status_code == 200
    db = SessionLocal()
    try:
        row = db.query(NotificationChannelConfig).filter_by(channel="dingtalk").one()
        # 模拟密钥轮换：库中密文仍是旧 key 加密，运行时 key 已变成新值
        assert row.webhook_url_encrypted
        monkeypatch.setattr(config, "SECRET_KEY", "rotated-key-xyz")
        db.add(NotificationOutbox(title="批", content="", ntype="system", idempotency_key=str(uuid.uuid4())))
        db.commit()
        # 解析安全降级
        resolved = channel_settings.resolve_dingtalk(db)
        assert resolved["enabled"] is False and resolved["webhook_url"] == ""
        # 投递批次安全完成（disabled），不抛异常
        stats = notify_channels.deliver_outbox(db)
        assert stats["disabled"] == 1
    finally:
        db.close()
