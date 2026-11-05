"""The schema starts at one baseline; databases from before it are moved aside untouched and the app starts empty."""
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app import config
from app import db as database
from app.db import Base


def test_the_baseline_builds_exactly_the_models(client):
    with database.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection, opts={'compare_server_default': True}), Base.metadata)
    assert diff == []
    assert database.old_database_revision() is None


def _old_tables(connection, revision):
    connection.exec_driver_sql('CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, name VARCHAR(200))')
    connection.exec_driver_sql("INSERT INTO projects VALUES ('p-old', '旧项目')")
    if revision is not None:
        connection.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)')
        connection.exec_driver_sql(f"INSERT INTO alembic_version VALUES ('{revision}')")


@pytest.mark.parametrize('revision', ['g3a94b000001', None])
def test_an_old_sqlite_database_and_its_files_move_aside(monkeypatch, tmp_path, revision):
    data = tmp_path / 'data'
    (data / 'uploads' / 'ab').mkdir(parents=True)
    (data / 'uploads' / 'ab' / 'file.bin').write_bytes(b'old bytes')
    (data / 'backups').mkdir()
    (data / 'secret.key').write_text('keep')
    engine = sa.create_engine(f"sqlite:///{data / 'agvpm.db'}")
    with engine.begin() as connection:
        _old_tables(connection, revision)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, '_is_sqlite', True)
    monkeypatch.setattr(config, 'DATA_DIR', data)
    monkeypatch.setattr(config, 'UPLOAD_DIR', data / 'uploads')

    assert database.old_database_revision() == (revision or '无版本')
    place = database._set_aside_old_database()

    folders = [path for path in data.iterdir() if path.name.startswith('old-')]
    assert len(folders) == 1 and place == str(folders[0] / 'agvpm.db')
    old = sa.create_engine(f'sqlite:///{place}')
    with old.connect() as connection:
        assert connection.exec_driver_sql('SELECT name FROM projects').scalar() == '旧项目'
    old.dispose()
    assert (folders[0] / 'uploads' / 'ab' / 'file.bin').read_bytes() == b'old bytes'
    assert (data / 'uploads').is_dir() and not any((data / 'uploads').iterdir())
    assert (data / 'backups').is_dir() and (data / 'secret.key').read_text() == 'keep'
    # The database file is gone from its place, so the next start builds an empty one.
    assert not (data / 'agvpm.db').exists()
    assert database.old_database_revision() is None
    engine.dispose()


def test_a_database_on_the_baseline_or_empty_is_not_old(monkeypatch, tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(database, 'engine', engine)
    assert database.old_database_revision() is None
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)')
    assert database.old_database_revision() is None
    engine.dispose()


@pytest.mark.skipif(not os.environ.get('DATABASE_URL', '').startswith('postgresql'), reason='PostgreSQL only')
def test_an_old_postgres_schema_moves_to_its_own_schema(monkeypatch, tmp_path):
    url = os.environ['DATABASE_URL']
    admin = sa.create_engine(url)
    with admin.begin() as connection:
        connection.exec_driver_sql('DROP SCHEMA IF EXISTS baseline_probe CASCADE')
        connection.exec_driver_sql('CREATE SCHEMA baseline_probe')
    engine = sa.create_engine(url, connect_args={'options': '-csearch_path=baseline_probe'})
    moved = None
    try:
        with engine.begin() as connection:
            _old_tables(connection, 'g3a94b000001')
            connection.exec_driver_sql("CREATE TYPE probe_state AS ENUM ('a', 'b')")
            connection.exec_driver_sql('CREATE TABLE notes (id SERIAL PRIMARY KEY, state probe_state)')
            connection.exec_driver_sql("INSERT INTO notes (state) VALUES ('a')")
        data = tmp_path / 'data'
        (data / 'uploads').mkdir(parents=True)
        monkeypatch.setattr(database, 'engine', engine)
        monkeypatch.setattr(database, '_is_sqlite', False)
        monkeypatch.setattr(config, 'DATA_DIR', data)
        monkeypatch.setattr(config, 'UPLOAD_DIR', data / 'uploads')

        place = database._set_aside_old_database()
        moved = place.split()[-1]
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM pg_class WHERE relnamespace = 'baseline_probe'::regnamespace").scalar() == 0
            assert connection.exec_driver_sql(f'SELECT name FROM "{moved}".projects').scalar() == '旧项目'
            assert connection.exec_driver_sql(f'SELECT state::text FROM "{moved}".notes').scalar() == 'a'
        assert database.old_database_revision() is None
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql('DROP SCHEMA IF EXISTS baseline_probe CASCADE')
            if moved:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{moved}" CASCADE')
        admin.dispose()
