"""存量 admin 密码显式轮换流程测试（seed_all 的 ADMIN_PASSWORD_ROTATE 分支）。

安全、显式、不可泄密：
- 显式：仅 ADMIN_PASSWORD_ROTATE=1 时轮换，不会在每次启动静默改密；
- 安全：轮换后 token_version +1，所有已登录会话立即失效；
- 幂等：密码未变则跳过（不重哈希、不失效会话）；
- 不可泄密：明文只来自环境变量，不写日志、不落盘（此处验证行为而非日志）。
"""

import pytest
from passlib.context import CryptContext


def _admin(db):
    from app.models import User
    return db.query(User).filter_by(username="admin").first()


def test_rotation_is_explicit_and_bumps_token_version(client, monkeypatch):
    """开启轮换标志 + 新密码 → 改密成功、旧密码失效、旧会话全部失效。"""
    from app.db import SessionLocal
    from app.seed.seed_data import seed_all

    pwd = CryptContext(schemes=["bcrypt"])
    db = SessionLocal()
    try:
        admin = _admin(db)
        assert admin is not None
        old_tv = admin.token_version or 0
        # 演示模式默认 admin123 可登录
        assert pwd.verify("admin123", admin.password_hash)

        monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "NewAdminPass!1")
        # 未开启轮换标志 → 保持原密码与 token_version 不变
        monkeypatch.delenv("ADMIN_PASSWORD_ROTATE", raising=False)
        seed_all(db)
        db.refresh(admin)
        assert (admin.token_version or 0) == old_tv
        assert not pwd.verify("NewAdminPass!1", admin.password_hash)

        # 开启轮换 → 改密 + token_version +1（旧会话全部失效）
        monkeypatch.setenv("ADMIN_PASSWORD_ROTATE", "1")
        seed_all(db)
        db.refresh(admin)
        assert (admin.token_version or 0) == old_tv + 1
        assert pwd.verify("NewAdminPass!1", admin.password_hash)
        assert not pwd.verify("admin123", admin.password_hash)
    finally:
        db.close()


def test_rotation_is_idempotent_when_password_unchanged(client, monkeypatch):
    """同密码再次轮换 → 幂等跳过，不重复失效会话。"""
    from app.db import SessionLocal
    from app.seed.seed_data import seed_all

    db = SessionLocal()
    try:
        admin = _admin(db)
        monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "Rotate12345!")
        monkeypatch.setenv("ADMIN_PASSWORD_ROTATE", "1")
        seed_all(db)
        db.refresh(admin)
        tv_after_first = admin.token_version or 0

        seed_all(db)  # 同密码第二次
        db.refresh(admin)
        assert (admin.token_version or 0) == tv_after_first
    finally:
        db.close()


def test_rotation_requires_password_when_enabled(client, monkeypatch):
    """开启轮换但未提供新密码 → 启动报错（fail-closed，不静默）。"""
    from app.db import SessionLocal
    from app.seed.seed_data import seed_all

    monkeypatch.setenv("ADMIN_PASSWORD_ROTATE", "1")
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("DEMO_ADMIN_PASSWORD", raising=False)

    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_ROTATE"):
            seed_all(db)
    finally:
        db.close()


def test_rotation_short_password_rejected(client, monkeypatch):
    """新密码不足 8 位 → 拒绝（不采用弱口令）。"""
    from app.db import SessionLocal
    from app.seed.seed_data import seed_all

    monkeypatch.setenv("ADMIN_PASSWORD_ROTATE", "1")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "short")

    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError, match="至少 8 位"):
            seed_all(db)
    finally:
        db.close()
