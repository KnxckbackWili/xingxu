"""Alembic entry: the schema starts at the baseline revision and grows by later revisions.

Databases from before the baseline are not upgraded; app/db.py moves them aside first.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

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
    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'}, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def _upgrade(connection):
    # SQLite rebuilds a table to alter it (batch mode); foreign keys stay off meanwhile so the
    # rebuild cannot cascade into child rows, and are checked before the transaction ends.
    sqlite = connection.dialect.name == 'sqlite'
    if sqlite:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
    try:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                violation = connection.exec_driver_sql('PRAGMA foreign_key_check').fetchone()
                if violation is not None:
                    raise RuntimeError(f'迁移后外键核对失败：表={violation[0]} 行={violation[1]}')
        connection.commit()
    finally:
        if sqlite:
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            connection.commit()


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
