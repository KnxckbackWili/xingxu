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
    """A freshly migrated and seeded database for every test."""
    import shutil
    from app.config import UPLOAD_DIR
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
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    from app.routers.auth import reset_login_failures
    if restored or not postgres:
        reset_login_failures()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        if file_sqlite and not restored:
            _sqlite_save(engine)
        if postgres and not restored:
            _pg_save(engine)
        yield c


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.cookies.clear()  # tests name the caller explicitly, with a Bearer header
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return _login(client, "admin", "admin123")


@pytest.fixture()
def staff(client):
    """An employee (张伟)."""
    return _login(client, "zhangwei", "demo12345")


@pytest.fixture()
def staff2(client):
    """A second employee (李娜), for two people editing at once."""
    return _login(client, "lina", "demo12345")


@pytest.fixture()
def project(client, staff):
    """A project made from the built-in template, with three vehicles."""
    template = client.get("/api/templates", headers=staff).json()[0]
    response = client.post("/api/projects", headers=staff, json={
        "name": "苏州工厂", "contract_no": "HT-2026-001", "customer": "某客户", "template_id": template["id"], "vehicle_count": 3})
    assert response.status_code == 200, response.text
    return client.get(f"/api/projects/{response.json()['id']}", headers=staff).json()
