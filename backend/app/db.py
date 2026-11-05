"""Database engine, session, and initialization."""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import DATABASE_URL

_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # SQLite with WAL mode for concurrent reads
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
        # 100-concurrent-user target: FastAPI's default threadpool is ~40, so the
        # connection pool must cover peak requests. SQLite WAL supports concurrent
        # readers; writes are serialized by busy_timeout.
        pool_size=10,
        max_overflow=40,
        pool_timeout=10,
    )
else:
    # PostgreSQL（A1/E4）：pool_pre_ping 处理断开的空闲连接；pool_recycle 防长连接失效。
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=40,
        pool_timeout=10,
        pool_pre_ping=True,
        pool_recycle=1800,
    )

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _backup_before_migrate():
    """Best-effort encrypted DB snapshot; failures remain explicit on stderr.

    Every invocation owns a unique destination, including workers started in the
    same second. Historical plaintext snapshots are retained; only new encrypted
    snapshots participate in the existing twenty-file rotation.
    """
    import shutil
    import sqlite3
    import subprocess
    import sys
    import tempfile
    import time
    from pathlib import Path
    from urllib.parse import unquote, urlparse
    from uuid import uuid4
    from app.config import DATA_DIR
    from app.services.backup_crypto import get_passphrase, encrypt_file

    backups_dir = DATA_DIR / "backups"
    try:
        if backups_dir.is_symlink():
            raise ValueError("备份目录不能是链接")
        backups_dir.mkdir(parents=True, exist_ok=True)
        kind = "SQLite" if _is_sqlite else "PG"
        if _is_sqlite:
            source_file = engine.url.database
            if not source_file or source_file == ":memory:" or not Path(source_file).exists():
                return
        else:
            pg_dump = shutil.which("pg_dump")
            if not pg_dump:
                print("[db] 未找到 pg_dump，跳过迁移前 PG 备份", file=sys.stderr, flush=True)
                return
        password = get_passphrase(DATA_DIR)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = "db" if _is_sqlite else "sql"
        destination = backups_dir / f"agvpm-before-migrate-{stamp}-{uuid4().hex}.{suffix}.agvenc"
        with tempfile.TemporaryDirectory(prefix=".before-migrate-", dir=backups_dir) as temp:
            snapshot = Path(temp) / ("database." + suffix)
            descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            if _is_sqlite:
                source = engine.raw_connection()
                try:
                    with sqlite3.connect(snapshot) as target:
                        source.driver_connection.backup(target)
                finally:
                    source.close()
            else:
                url = urlparse(DATABASE_URL)
                cmd = [pg_dump, "-h", url.hostname or "127.0.0.1", "-p", str(url.port or 5432),
                       "-U", unquote(url.username or "agv"), "-d", unquote((url.path or "/agvpm").lstrip("/")),
                       "--no-owner", "--no-privileges", "-f", str(snapshot)]
                result = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                        env={**os.environ, "PGPASSWORD": unquote(url.password or "agv")})
                if result.returncode:
                    detail = (result.stderr or "").strip() or "无错误输出"
                    if url.password:
                        detail = detail.replace(unquote(url.password), "[REDACTED]")
                    print(f"[db] 迁移前 PG 备份失败（pg_dump rc={result.returncode}）: {detail}", file=sys.stderr, flush=True)
                    return
            encrypt_file(snapshot, destination, password)
        print(f"[db] 迁移前 {kind} 备份成功: {destination}", file=sys.stderr, flush=True)
        candidates = sorted((path for path in backups_dir.glob("agvpm-before-migrate-*.agvenc") if not path.is_symlink()),
                            key=lambda path: (path.stat().st_mtime_ns, path.name))
        for old in candidates[:-20]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception as error:
        print(f"[db] 迁移前备份跳过（{type(error).__name__}: {error}）", file=sys.stderr, flush=True)


def _alembic_config():
    from alembic.config import Config
    from app.config import BASE_DIR

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    return cfg


def _alembic_sync_schema():
    """Create or upgrade the schema from the baseline revision."""
    from alembic import command

    cfg = _alembic_config()
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def old_database_revision():
    """The revision of a database from before the current baseline, or None when it can be upgraded.

    An empty database, or one already on a known revision, is not old. Tables without a
    version, or a version the scripts do not know, are old.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names()) - {"sqlite_sequence"}
        if not tables - {"alembic_version"}:
            return None
        if "alembic_version" not in tables:
            return "无版本"
        versions = {row[0] for row in connection.exec_driver_sql("SELECT version_num FROM alembic_version")}
    known = {script.revision for script in ScriptDirectory.from_config(_alembic_config()).walk_revisions()}
    if versions and versions <= known:
        return None
    return "、".join(sorted(versions)) or "无版本"


# Data that belongs to the database rows; it moves aside with an old database.
_ROW_DATA_DIRS = ("uploads", "migration-exports", "project-deletion-backups")


def _set_aside_old_database():
    """Move a database from before the baseline (and its files) aside, untouched, so the app starts empty.

    SQLite: the file goes to DATA_DIR/old-<time>/. PostgreSQL: every object of the schema
    moves to a schema old_<time>. Uploaded files of those rows go to DATA_DIR/old-<time>/.
    Nothing is deleted; backups, keys and update records stay where they are.
    """
    import shutil
    import sys
    import time
    from pathlib import Path
    from app.config import DATA_DIR

    revision = old_database_revision()
    if revision is None:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = DATA_DIR / f"old-{stamp}"
    folder.mkdir(parents=True, exist_ok=False)
    if _is_sqlite:
        engine.dispose()
        database = Path(engine.url.database)
        for suffix in ("", "-wal", "-shm", "-journal"):
            source = Path(str(database) + suffix)
            if source.exists():
                shutil.move(str(source), str(folder / source.name))
        place = str(folder / database.name)
    else:
        schema = "old_" + stamp.replace("-", "_")
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            here = "c.relnamespace = current_schema()::regnamespace"
            kinds = {"r": "TABLE", "p": "TABLE", "f": "FOREIGN TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW"}
            for name, kind in connection.exec_driver_sql(
                    f"SELECT c.relname, c.relkind FROM pg_class c WHERE {here} AND c.relkind IN ('r','p','f','v','m') "
                    "AND NOT c.relispartition").all():
                connection.exec_driver_sql(f'ALTER {kinds[kind]} "{name}" SET SCHEMA "{schema}"')
            for (name,) in connection.exec_driver_sql(f"SELECT c.relname FROM pg_class c WHERE {here} AND c.relkind = 'S'").all():
                connection.exec_driver_sql(f'ALTER SEQUENCE "{name}" SET SCHEMA "{schema}"')
            for name, kind in connection.exec_driver_sql(
                    "SELECT t.typname, t.typtype FROM pg_type t WHERE t.typnamespace = current_schema()::regnamespace "
                    "AND t.typtype IN ('e','d') ").all():
                connection.exec_driver_sql(f'ALTER {"DOMAIN" if kind == "d" else "TYPE"} "{name}" SET SCHEMA "{schema}"')
            for name, arguments in connection.exec_driver_sql(
                    "SELECT p.proname, pg_get_function_identity_arguments(p.oid) FROM pg_proc p "
                    "WHERE p.pronamespace = current_schema()::regnamespace").all():
                connection.exec_driver_sql(f'ALTER ROUTINE "{name}"({arguments}) SET SCHEMA "{schema}"')
        place = f"PostgreSQL 架构 {schema}"
    for name in _ROW_DATA_DIRS:
        source = DATA_DIR / name
        if source.exists() and not source.is_symlink():
            shutil.move(str(source), str(folder / name))
    from app.config import UPLOAD_DIR
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[db] 发现旧版本数据库（{revision}），已原样移到 {place}，相关文件在 {folder}；系统从空库开始",
          file=sys.stderr, flush=True)
    return place


# PG 多 worker（uvicorn --workers 每个 worker 各跑一次 lifespan/init_db）首启时，
# Alembic/seed 并发互踩会导致一个 worker 崩溃（如 duplicate table/column，
# 恢复演练里 CREATE TABLE ai_usage_ledger 就是被并发 create_all 打死的）。用会话级
# advisory lock 串行化 schema 初始化：先到者建表/迁移/seed，其余 worker 阻塞在锁上，
# 等持有者释放后重跑（此时表/列已存在 → 幂等 no-op），保证空库/恢复后首启不崩。
_ADVISORY_LOCK_KEY = 72109241


def init_db():
    """Upgrade the schema through Alembic, then seed default data."""
    if _is_sqlite:
        _init_db()
        return
    from sqlalchemy import text
    conn = engine.connect()
    try:
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY}).fetchone()
        _init_db()
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY}).fetchone()
        conn.close()


def _init_db():
    """实际初始化：_init_db 由 init_db 在 PG advisory lock（多 worker 串行化）下调用。

    SQLite 单进程直接调用（无锁路径不变）。
    """
    _backup_before_migrate()
    import app.models  # noqa: F401 - ensure models are registered
    _set_aside_old_database()
    _alembic_sync_schema()

    # Seed default roles, admin user, and template
    from app.seed.seed_data import (seed_all, seed_template_procurements, seed_task_documents,
                                    seed_vehicle_types, seed_template_preparations)
    db = SessionLocal()
    try:
        seed_all(db)
        from app.seed.default_template import seed_default_template
        seed_default_template(db)
        # These seeds previously lived inside the SQLite-only migration branch.
        seed_template_preparations(db)
        from app.seed.scope_preparations import migrate_scope_preparations
        migrate_scope_preparations(db)
        # 常用采购项库独立 seed（幂等）：seed_all 有 admin 守卫，旧库会早退。
        seed_template_procurements(db)
        seed_task_documents(db)
        # HYPE-63：预置车型字典（幂等，独立于 seed_all 守卫，旧库也补齐）
        seed_vehicle_types(db)
        # 所有账号都能看、都能记录所有项目：补齐旧项目的成员名单（开关关闭时不做任何事）。
        from app.services.open_access import reconcile
        reconcile(db)
        db.commit()
    finally:
        db.close()
