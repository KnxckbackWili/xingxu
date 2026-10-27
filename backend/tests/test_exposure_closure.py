"""暴露面闭环回归测试（P0-复查阻断项）。

覆盖三类修复：
  1. `docker/start.sh`：启动日志不回显数据库口令（DB URL 脱敏）。
  2. `app/db.py::_backup_before_migrate()`：PG 分支显式走 TCP 127.0.0.1:5432
     （容器内 socket 在 /tmp，默认 /var/run/postgresql 不存在），且失败/成功均可见。
  3. `app/seed/seed_data.py::seed_all`：生产 SEED_DEMO_USERS=0 时，
     - 全新库只建 admin、不建演示账号；
     - 仍持默认口令（pm123/worker123）的存量演示账号被幂等禁用并失效旧会话；
     - 已轮换为强口令的演示账号保持可用（不被误禁用）。
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ===== 1. start.sh DB URL 脱敏 =====

def test_start_sh_db_url_redacted():
    """start.sh 的 PG 启动日志不得回显口令，且脱敏逻辑真实生效。"""
    start = (REPO_ROOT / "docker" / "start.sh").read_text(encoding="utf-8")

    # 直接回显 $DATABASE_URL（含口令）的泄漏行必须已移除
    assert "已启用容器内 PostgreSQL → $DATABASE_URL" not in start
    assert "_masked_db_url=" in start

    # 抽取 start.sh 中实际的三行（export + 脱敏 + echo）原样执行，验证回显不含口令
    snippet = [
        line for line in start.splitlines()
        if line.strip().startswith("export DATABASE_URL=")
        or line.strip().startswith("_masked_db_url=")
        or "已启用容器内 PostgreSQL" in line
    ]
    assert len(snippet) == 3, f"未按预期找到 3 行脱敏片段: {snippet}"
    r = subprocess.run(["sh", "-c", "\n".join(snippet)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "agv:agv@" not in r.stdout, f"启动日志泄漏数据库口令: {r.stdout}"
    assert "agv:***@" in r.stdout


# ===== 2. _backup_before_migrate() PG 分支 =====

class _FakeResult:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def _patch_pg_backup(monkeypatch, tmp_path, result):
    import shutil as real_shutil
    import subprocess as real_subprocess
    import app.db as db_mod

    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        if result.returncode == 0:
            from pathlib import Path
            Path(argv[argv.index("-f") + 1]).write_bytes(b"-- controlled SQL snapshot")
        return result

    monkeypatch.setattr(db_mod, "_is_sqlite", False)
    monkeypatch.setattr(
        db_mod,
        "DATABASE_URL",
        "postgresql://backup_user:backup_pass@pg-backup.internal:5544/agvpm_custom",
    )
    monkeypatch.setattr(real_shutil, "which",
                        lambda name: "/fake/bin/pg_dump" if name == "pg_dump" else None)
    monkeypatch.setattr(real_subprocess, "run", fake_run)
    monkeypatch.setattr("app.config.DATA_DIR", tmp_path)
    from app.services.backup_crypto import set_passphrase
    set_passphrase(tmp_path, "test-only-backup-password-2026")
    return db_mod, calls


def test_backup_before_migrate_pg_uses_tcp_and_surfaces_failure(monkeypatch, tmp_path, capsys):
    """PG 备份必须显式走 TCP 连接参数；失败必须写 stderr（不再静默吞掉）。"""
    result = _FakeResult(returncode=1, stderr="connection to server on socket ... failed")
    db_mod, calls = _patch_pg_backup(monkeypatch, tmp_path, result)

    db_mod._backup_before_migrate()

    argv = calls["argv"]
    assert "-h" in argv and "pg-backup.internal" in argv
    assert "-p" in argv and "5544" in argv
    assert "-U" in argv and "backup_user" in argv
    assert "agvpm_custom" in argv
    assert calls["kwargs"]["env"]["PGPASSWORD"] == "backup_pass"

    err = capsys.readouterr().err
    assert "迁移前 PG 备份失败" in err
    assert "connection to server" in err, f"具体错误应可见: {err}"


def test_backup_before_migrate_pg_success_visible(monkeypatch, tmp_path, capsys):
    """PG 备份成功时也有可见日志，运维可确认迁移前备份确实发生。"""
    result = _FakeResult(returncode=0)
    db_mod, _ = _patch_pg_backup(monkeypatch, tmp_path, result)

    db_mod._backup_before_migrate()

    assert "迁移前 PG 备份成功" in capsys.readouterr().err


# ===== 3. seed_all 演示账号暴露面收口 =====

def _demo_names():
    return ("pm", "worker1", "worker2")


def test_prod_seed_creates_admin_only(monkeypatch):
    """SEED_DEMO_USERS=0 的全新库只建 admin，不创建任何演示账号。"""
    from app.db import Base, engine, SessionLocal, init_db
    from app.models import User

    monkeypatch.setenv("SEED_DEMO_USERS", "0")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "ProdBootPass!2026")
    monkeypatch.delenv("ADMIN_PASSWORD_ROTATE", raising=False)

    Base.metadata.drop_all(bind=engine)
    from sqlalchemy import text
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS alembic_version'))
    try:
        init_db()
        db = SessionLocal()
        try:
            usernames = {u.username for u in db.query(User).all()}
            assert usernames == {"admin"}
        finally:
            db.close()
    finally:
        Base.metadata.drop_all(bind=engine)  # 恢复，避免影响后续用例
        with engine.begin() as connection:
            connection.execute(text('DROP TABLE IF EXISTS alembic_version'))
        from app.db import init_db as _reinit
        _reinit()


def test_prod_seed_disables_default_demo_users(client, monkeypatch):
    """SEED_DEMO_USERS=0 时，仍持默认口令的存量演示账号被幂等禁用并使旧会话失效。"""
    from app.db import SessionLocal
    from app.models import User
    from app.seed.seed_data import seed_all

    monkeypatch.setenv("SEED_DEMO_USERS", "0")
    monkeypatch.delenv("ADMIN_PASSWORD_ROTATE", raising=False)

    db = SessionLocal()
    try:
        seed_all(db)
        db.commit()
        for name in _demo_names():
            u = db.query(User).filter_by(username=name).first()
            assert u is not None
            assert u.is_active is False, f"{name} 应被禁用"
            assert (u.token_version or 0) == 1, f"{name} 旧会话应失效"
        # 幂等：再次 seed 不重复失效会话
        seed_all(db)
        db.commit()
        for name in _demo_names():
            u = db.query(User).filter_by(username=name).first()
            assert (u.token_version or 0) == 1
    finally:
        db.close()

    # 禁用账号登录被拒（403 已停用）
    r = client.post("/api/auth/login", json={"username": "pm", "password": "pm123"})
    assert r.status_code == 403


def test_rotated_demo_users_not_disabled_by_prod_seed(client, monkeypatch):
    """已轮换为强口令的演示账号在 SEED_DEMO_USERS=0 时保持可用（不被误禁用）。"""
    from passlib.context import CryptContext
    from app.db import SessionLocal
    from app.models import User
    from app.seed.seed_data import seed_all

    pwd = CryptContext(schemes=["bcrypt"])
    creds = {
        "pm": "Str0ng-Pm-2026!",
        "worker1": "Str0ng-W1-2026!",
        "worker2": "Str0ng-W2-2026!",
    }
    db = SessionLocal()
    try:
        for name, pw in creds.items():
            u = db.query(User).filter_by(username=name).first()
            assert u is not None
            u.password_hash = pwd.hash(pw)
            u.token_version = (u.token_version or 0) + 1
        db.commit()

        monkeypatch.setenv("SEED_DEMO_USERS", "0")
        monkeypatch.delenv("ADMIN_PASSWORD_ROTATE", raising=False)
        seed_all(db)
        db.commit()

        for name in _demo_names():
            u = db.query(User).filter_by(username=name).first()
            assert u.is_active is True, f"{name} 不应被禁用"
            assert (u.token_version or 0) == 1
    finally:
        db.close()

    # 新强口令（合法新凭据）可用；旧默认口令已 401
    for name, pw in creds.items():
        r = client.post("/api/auth/login", json={"username": name, "password": pw})
        assert r.status_code == 200, (name, r.text)
    r = client.post("/api/auth/login", json={"username": "pm", "password": "pm123"})
    assert r.status_code == 401
