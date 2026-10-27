"""Test fixtures: fresh isolated DB per test function.

One engine/module set (imported once with a temp DATA_DIR); each test
drops and recreates all tables so tests never leak state.
"""

import os
import sys
import tempfile

TEST_DIR = tempfile.mkdtemp(prefix="agvpm-test-")
os.environ["DATA_DIR"] = TEST_DIR
# 定时调度器默认关：容器/开发 shell 可能 export 过 SCHEDULER_ENABLED=1，
# 这里强制覆盖，防止每个用例的 TestClient 都连带启动调度线程（与 drop_all 竞态）。
os.environ["SCHEDULER_ENABLED"] = "0"
# 聚合看板 TTL 缓存强制关：缓存键按 user.id 缓存 15s，跨用例会返回旧项目/旧进度
# （例：先跑一个项目的 overview 会把结果缓存，下个用例同用户直接命中旧缓存）。
os.environ["AGVPM_ENABLE_CACHE"] = "0"
os.environ["SEED_DEMO_USERS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


_SQLITE_SNAPSHOT = os.path.join(TEST_DIR, "migrated-seed-snapshot.db")


def _sqlite_restore(engine):
    """Copy the freshly migrated + seeded snapshot over the test database.

    Equivalent to drop_all + a full Alembic upgrade + seed, without replaying
    the whole migration chain for every test. The page-level backup replaces
    schema and rows, including any table a previous test altered.
    """
    import sqlite3
    engine.dispose()
    source = sqlite3.connect(_SQLITE_SNAPSHOT)
    target = sqlite3.connect(engine.url.database)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _sqlite_save(engine):
    import sqlite3
    source = sqlite3.connect(engine.url.database)
    target = sqlite3.connect(_SQLITE_SNAPSHOT)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


@pytest.fixture()
def client():
    """Fresh tables + seed per test."""
    from app.db import engine, Base, _is_sqlite
    import app.models  # Register metadata before deleting a reused external test DB.
    file_sqlite = _is_sqlite and bool(engine.url.database)
    restored = file_sqlite and os.path.exists(_SQLITE_SNAPSHOT)
    if restored:
        _sqlite_restore(engine)
    else:
        Base.metadata.drop_all(bind=engine)
        from sqlalchemy import text
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    # 限流状态按用户全局累计，跨用例会误伤导出/登录测试 → 每个用例清空
    from app.services.rate_limit import reset_rate_limits
    reset_rate_limits()
    from app.services.ai_jobs import reset_ai_rate_limits
    reset_ai_rate_limits()
    from app.routers.auth import reset_login_failures
    reset_login_failures()
    # The app lifespan runs init_db() → alembic upgrade head + seed on startup
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        if file_sqlite and not restored:
            _sqlite_save(engine)
        # Business fixtures represent a configured isolated installation. #85
        # requires encrypted project evidence before deletion; missing-password
        # behavior has dedicated tests with their own fresh DATA_DIR.
        from app.config import DATA_DIR
        from app.services.backup_crypto import set_passphrase
        set_passphrase(DATA_DIR, 'test-only-backup-password-2026')
        yield c


@pytest.fixture()
def admin_headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def pm_headers(client):
    r = client.post("/api/auth/login", json={"username": "pm", "password": "pm123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def worker_headers(client):
    r = client.post("/api/auth/login", json={"username": "worker1", "password": "worker123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def tech_headers(client, admin_headers):
    """technician 角色登录态（测试库每用例重建，不存在则创建）。"""
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "tech", "password": "Review123!",
        "display_name": "技术工程师-测试", "role": "technician"})
    if r.status_code != 200 and "已存在" not in r.text:
        raise AssertionError(r.text)
    r = client.post("/api/auth/login", json={"username": "tech", "password": "Review123!"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def lead_headers(client, admin_headers):
    """lead 角色登录态（测试库每用例重建，不存在则创建）。"""
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "lead", "password": "Review123!",
        "display_name": "技术经理-测试", "role": "lead"})
    if r.status_code != 200 and "已存在" not in r.text:
        raise AssertionError(r.text)
    r = client.post("/api/auth/login", json={"username": "lead", "password": "Review123!"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def upgrade_legacy_schema():
    """Exercise the frozen legacy repair without replaying already-applied v3 DDL.

    client already applied the current full chain. Only T01 alignment and its
    T03 retirement cleanup are being exercised by these historical tests; keep
    later feature tables/columns and restore their already-applied revision.
    Dedicated migration tests exercise each actual forward chain independently.
    """
    from app.db import engine
    from app.config import BASE_DIR
    from sqlalchemy import text
    from alembic import command
    from alembic.config import Config

    def upgrade():
        with engine.begin() as connection:
            original = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            connection.execute(text("DELETE FROM change_logs WHERE entity_type='migration' AND entity_id='g3a03b000001'"))
            connection.execute(text("UPDATE alembic_version SET version_num='d2e7f9a103b4'"))
        cfg = Config(str(BASE_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
        with engine.connect() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "g3a03b000001")
        with engine.connect() as connection:
            cfg.attributes["connection"] = connection
            command.stamp(cfg, original)
    return upgrade


@pytest.fixture()
def backup_passphrase(client):
    """Explicitly enable encrypted backups only in backup workflow tests."""
    from app.config import DATA_DIR
    from app.services.backup_crypto import set_passphrase
    password = "test-only-backup-password-2026"
    set_passphrase(DATA_DIR, password)
    return password
