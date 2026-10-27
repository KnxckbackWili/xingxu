"""Test fixtures: fresh isolated DB per test function.

One engine/module set (imported once with a temp DATA_DIR). The first test
drops all tables and runs the full Alembic chain + seed; later tests restore
that state (SQLite: page snapshot; PostgreSQL: row snapshot, with a full
rebuild whenever a test changed the schema), so tests never leak state.
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


# PostgreSQL equivalent: the migrated + seeded rows of the dedicated test DB,
# kept in memory and copied back after TRUNCATE. Any schema change made by a
# test (fingerprint differs) falls back to drop_all + the full Alembic chain.
_PG_SNAPSHOT = {}
_PG_FINGERPRINT = """
SELECT md5(
  coalesce((SELECT string_agg(table_name||'.'||column_name||':'||data_type||':'||is_nullable||':'||
                              coalesce(column_default,'')||':'||coalesce(character_maximum_length::text,''),
                              ',' ORDER BY table_name, column_name)
            FROM information_schema.columns WHERE table_schema = current_schema()), '') ||
  coalesce((SELECT string_agg(conrelid::regclass::text||':'||conname||':'||pg_get_constraintdef(oid),
                              ',' ORDER BY conrelid::regclass::text, conname)
            FROM pg_constraint WHERE connamespace = current_schema()::regnamespace), '') ||
  coalesce((SELECT string_agg(indexdef, ',' ORDER BY indexdef) FROM pg_indexes WHERE schemaname = current_schema()), '') ||
  coalesce((SELECT string_agg(t.tgrelid::regclass::text||':'||t.tgname, ',' ORDER BY t.tgrelid::regclass::text, t.tgname)
            FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
            WHERE c.relnamespace = current_schema()::regnamespace AND NOT t.tgisinternal), '') ||
  coalesce((SELECT string_agg(proname||':'||md5(prosrc), ',' ORDER BY proname, md5(prosrc))
            FROM pg_proc WHERE pronamespace = current_schema()::regnamespace), ''))
"""


def _pg_tables(cursor):
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename")
    return [row[0] for row in cursor.fetchall()]


def _pg_save(engine):
    import io
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute(_PG_FINGERPRINT)
        fingerprint = cursor.fetchone()[0]
        data = {}
        for table in _pg_tables(cursor):
            buffer = io.StringIO()
            cursor.copy_expert(f'COPY "{table}" TO STDOUT', buffer)
            data[table] = buffer.getvalue()
        cursor.execute("SELECT sequencename, start_value, last_value FROM pg_sequences WHERE schemaname = current_schema()")
        sequences = cursor.fetchall()
        raw.rollback()
    finally:
        raw.close()
    _PG_SNAPSHOT.update(fingerprint=fingerprint, data=data, sequences=sequences)


def _pg_restore(engine):
    """Reset rows to the snapshot; False (no change) when the schema differs."""
    import io
    if not _PG_SNAPSHOT:
        return False
    engine.dispose()
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute(_PG_FINGERPRINT)
        if cursor.fetchone()[0] != _PG_SNAPSHOT['fingerprint'] or set(_pg_tables(cursor)) != set(_PG_SNAPSHOT['data']):
            raw.rollback()
            return False
        try:
            # The snapshot is a consistent copy, so FK triggers can be skipped while loading it.
            cursor.execute("SET LOCAL session_replication_role = replica")
        except Exception:
            raw.rollback()
            return False  # not permitted for this role: use the full rebuild
        cursor.execute('TRUNCATE ' + ', '.join(f'"{table}"' for table in _PG_SNAPSHOT['data']))
        for table, rows in _PG_SNAPSHOT['data'].items():
            if rows:
                cursor.copy_expert(f'COPY "{table}" FROM STDIN', io.StringIO(rows))
        for name, start, last in _PG_SNAPSHOT['sequences']:
            cursor.execute('SELECT setval(%s, %s, %s)', (f'"{name}"', last if last is not None else start, last is not None))
        raw.commit()
        return True
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


@pytest.fixture()
def client():
    """Fresh tables + seed per test."""
    from app.db import engine, Base, _is_sqlite
    import app.models  # Register metadata before deleting a reused external test DB.
    file_sqlite = _is_sqlite and bool(engine.url.database)
    postgres = engine.url.get_backend_name() == "postgresql"
    restored = file_sqlite and os.path.exists(_SQLITE_SNAPSHOT)
    if restored:
        _sqlite_restore(engine)
    elif postgres and _pg_restore(engine):
        restored = True
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
        if postgres and not restored:
            _pg_save(engine)
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
