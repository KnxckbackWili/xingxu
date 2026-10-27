"""Run all schema changes through Alembic, including adoption of unversioned 2.4.3."""
import os
import sys
from logging.config import fileConfig

from alembic import context
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, inspect, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DATABASE_URL  # noqa: E402
import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402

config = context.config
config.set_main_option('sqlalchemy.url', DATABASE_URL.replace('%', '%%'))
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def run_migrations_offline():
    sqlite=config.get_main_option('sqlalchemy.url').startswith('sqlite')
    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'}, render_as_batch=True,
                      transactional_ddl=True)
    # SQLite batch DDL must not cascade into immutable evidence while rebuilding a
    # parent. Match the online wrapper, including transaction and FK restoration.
    if sqlite:context.execute('PRAGMA foreign_keys=OFF')
    try:
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:context.execute('PRAGMA foreign_key_check')
    finally:
        if sqlite:context.execute('PRAGMA foreign_keys=ON')


def _upgrade(connection):
    if connection.in_transaction():
        raise RuntimeError('迁移需要独立连接；拒绝提交调用者已有的事务')
    sqlite = connection.dialect.name == 'sqlite'
    foreign_keys = None
    if sqlite:
        foreign_keys = connection.exec_driver_sql('PRAGMA foreign_keys').scalar()
        connection.commit()
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
        # sqlite3 otherwise autocommits DDL outside its deferred transaction.
        connection.exec_driver_sql('BEGIN')
    try:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True, transactional_ddl=True)
        with context.begin_transaction():
            tables = set(inspect(connection).get_table_names())
            business_tables = tables - {'alembic_version', 'sqlite_sequence'}
            migration_fn = context.get_context().opts.get('fn')
            upgrading = getattr(migration_fn, '__name__', '') == 'upgrade'
            if upgrading and business_tables and 'alembic_version' not in tables:
                if not {'projects', 'users'} <= tables:
                    raise RuntimeError('数据库不是可识别的2.4.3存量库，拒绝自动标记迁移版本')
                from migrations.v243_alignment import align_schema, LEGACY_REVISION
                # Only the fixed old schema is adopted. Every later revision,
                # including data transformations, still runs through upgrade.
                align_schema(Operations(context.get_context()))
                context.get_context().stamp(ScriptDirectory.from_config(config), LEGACY_REVISION)
            elif upgrading and 'alembic_version' in tables and not business_tables:
                raise RuntimeError('数据库只剩迁移版本表，业务表缺失；请恢复备份')
            context.run_migrations()
            if sqlite and upgrading:
                violation = connection.exec_driver_sql('PRAGMA foreign_key_check').fetchone()
                if violation is not None:
                    raise RuntimeError(f'迁移后外键核对失败：表={violation[0]} 行={violation[1]}；原数据已回滚，请先核对备份')
        if sqlite:
            connection.commit()
    except BaseException:
        connection.rollback()
        if sqlite:
            # A commit event can fail after SQLAlchemy deactivates its transaction
            # while sqlite3 still owns BEGIN. Roll that physical handle back too.
            connection.connection.driver_connection.rollback()
        raise
    finally:
        if sqlite:
            try:
                connection.rollback()
                connection.connection.driver_connection.rollback()
                connection.exec_driver_sql('PRAGMA foreign_keys=ON' if foreign_keys else 'PRAGMA foreign_keys=OFF')
                if connection.exec_driver_sql('PRAGMA foreign_keys').scalar() != int(bool(foreign_keys)):
                    raise RuntimeError('Migration connection foreign keys could not be restored')
                connection.commit()
            except BaseException:
                connection.invalidate()
                raise


def run_migrations_online():
    connection = config.attributes.get('connection')
    if connection is not None:
        _upgrade(connection)
        return
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix='sqlalchemy.', poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            _upgrade(connection)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
