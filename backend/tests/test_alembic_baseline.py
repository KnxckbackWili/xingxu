"""T01: the complete chain upgrades empty, versioned and unversioned databases."""
import json
import shutil
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.sql.elements import ClauseElement
from app.config import BASE_DIR


@pytest.fixture(scope='module')
def alembic_config():
    cfg = Config(str(BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BASE_DIR / 'migrations'))
    return cfg


def database(monkeypatch, path):
    url = f'sqlite:///{path}'
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    return sa.create_engine(url)


def stable_reflection(value):
    # Partial-index predicates reflect as new TextClause objects every time.
    # Compare their full SQL text, retaining all index options and properties.
    if isinstance(value, ClauseElement):
        return str(value)
    if isinstance(value, dict):
        return {key: stable_reflection(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [stable_reflection(item) for item in value]
    return value


def schema(engine):
    # Keep the complete reflection snapshot on one physical connection. An
    # Engine-bound Inspector can borrow different pooled SQLite handles between
    # calls after threaded tests and report a mixed, stale schema snapshot.
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        return {table: {'columns': [{**column, 'type': str(column['type'])} for column in inspector.get_columns(table)], 'indexes': stable_reflection(inspector.get_indexes(table)),
                        'foreign_keys': inspector.get_foreign_keys(table),
                        'unique': inspector.get_unique_constraints(table)}
                for table in inspector.get_table_names()}


def test_alembic_baseline_renders_full_schema(alembic_config, capsys):
    command.upgrade(alembic_config, 'd2e7f9a103b4', sql=True)
    sql = capsys.readouterr().out
    for table in ('projects', 'users', 'phases', 'modules', 'tasks', 'check_items',
                  'schedule_entries', 'team_templates', 'ai_usage_ledger'):
        assert f'CREATE TABLE {table}' in sql
    assert 'ALTER TABLE users ADD COLUMN permission_overrides JSON' in sql
    assert "ALTER TABLE users ADD COLUMN permission_version INTEGER DEFAULT '0' NOT NULL" in sql
    with pytest.raises(RuntimeError, match='必须在线执行'):
        command.upgrade(alembic_config, 'head', sql=True)
    assert "version_num='g3a01b000001'" not in capsys.readouterr().out


def test_empty_database_migration_matches_every_model(alembic_config, monkeypatch, tmp_path):
    from app.db import Base
    engine = database(monkeypatch, tmp_path / 'empty.db')
    try:
        command.upgrade(alembic_config, 'head')
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection, opts={'compare_server_default': True}), Base.metadata) == []
            assert connection.execute(sa.text('SELECT version_num FROM alembic_version')).scalar() == ScriptDirectory.from_config(alembic_config).get_current_head()
    finally:
        engine.dispose()


@pytest.mark.parametrize('versioned', [False, True])
def test_v243_adoption_preserves_rows_before_explicit_lifecycle_migration(alembic_config, monkeypatch, tmp_path, versioned):
    from migrations.v243_schema import metadata
    engine = database(monkeypatch, tmp_path / f'v243-{versioned}.db')
    metadata.create_all(engine)  # A frozen historical fixture, never startup schema creation.
    states = ('draft', 'planning', 'preparing', 'ready', 'executing', 'commissioning', 'pilot',
              'acceptance', 'completed', 'archived', 'suspended', 'closed')
    with engine.begin() as connection:
        connection.execute(sa.text('PRAGMA user_version=2'))
        for index, state in enumerate(states):
            connection.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,version) VALUES (:id,:name,'2026-01-01','2026-12-31',:status,:version)"),
                               {'id': f'p-{index}', 'name': f'Original {state}', 'status': state, 'version': index})
        if versioned:
            connection.execute(sa.text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
            connection.execute(sa.text("INSERT INTO alembic_version VALUES ('d2e7f9a103b4')"))
        before = connection.execute(sa.text('SELECT id,name,status,version FROM projects ORDER BY id')).all()
        connection.execute(sa.text("INSERT INTO vehicles (id,project_id,vehicle_type,model_name,quantity) VALUES ('vehicle','p-0','潜伏式','Original vehicle',2)"))
    try:
        # T01 adoption preserves the original decisions. Later T28 explicitly
        # normalizes states and retains every original value as migration source.
        command.upgrade(alembic_config, 'g3a01b000001')
        with engine.connect() as connection:
            assert connection.execute(sa.text('SELECT id,name,status,version FROM projects ORDER BY id')).all() == before
        command.upgrade(alembic_config, 'head')
        expected_statuses = {'draft': 'preparing', 'planning': 'preparing', 'ready': 'preparing',
                             'commissioning': 'executing', 'pilot': 'executing', 'closed': 'suspended'}
        # T28 bumps every row once; the later stage merge bumps former ready rows again.
        expected = [(pid, name, expected_statuses.get(state, state), version + (2 if state == 'ready' else 1))
                    for pid, name, state, version in before]
        with engine.connect() as connection:
            assert connection.execute(sa.text('SELECT id,name,status,version FROM projects ORDER BY id')).all() == expected
            migrated = connection.execute(sa.text('SELECT id,suspension,legacy_lifecycle FROM projects ORDER BY id')).all()
            originals = {pid: state for pid, _, state, _ in before}
            for pid, suspension, source in migrated:
                original = originals[pid]
                evidence = json.loads(source)
                merge = evidence.pop('ready_merge', None)
                assert (merge is not None) == (original == 'ready')
                if merge:
                    assert merge == {'migration': 'g3a90b000001', 'original_status': 'ready', 'original_status_before': None}
                assert evidence == {'version': 1, 'original_status': original, 'original_suspension': None,
                                    'migration': 'g3a28b000001', 'requires_repair': original in ('suspended', 'closed')}
                context = json.loads(suspension)
                if original in ('suspended', 'closed'):
                    assert context['status_before'] is None and context['reason']
                else:
                    assert context == {}
            audit = json.loads(connection.execute(sa.text("SELECT detail FROM change_logs WHERE id='v3-manual-project-lifecycle-audit'")).scalar_one())
            assert audit == {'changed_projects': len(states), 'requires_repair': 2, 'audit_events_restored': 0}
            assert connection.execute(sa.text('SELECT id,quantity FROM vehicles')).all() == [('vehicle', 2)]
            assert connection.execute(sa.text('SELECT version_num FROM alembic_version')).scalar() == ScriptDirectory.from_config(alembic_config).get_current_head()
        after = schema(engine)
        command.upgrade(alembic_config, 'head')
        assert schema(engine) == after
        with engine.connect() as connection:
            assert connection.execute(sa.text('SELECT id,name,status,version FROM projects ORDER BY id')).all() == expected
            assert connection.execute(sa.text('SELECT id,suspension,legacy_lifecycle FROM projects ORDER BY id')).all() == migrated
    finally:
        engine.dispose()


def test_unversioned_adoption_does_not_skip_following_data_migrations(alembic_config, monkeypatch, tmp_path):
    from migrations.v243_schema import metadata
    engine = database(monkeypatch, tmp_path / 'future.db')
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text('PRAGMA user_version=2'))
        connection.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,version) VALUES ('legacy','Original','2026-01-01','2026-12-31','planning',4)"))
    scripts = tmp_path / 'migration-chain'
    shutil.copytree(BASE_DIR / 'migrations', scripts, ignore=shutil.ignore_patterns('__pycache__'))
    old_head = ScriptDirectory.from_config(alembic_config).get_current_head()
    (scripts / 'versions' / 'test_following_data.py').write_text(
        f"from alembic import op\nrevision='test_following_data'\ndown_revision={old_head!r}\n"
        "def upgrade():\n    op.execute(\"UPDATE projects SET version=version+1 WHERE id='legacy'\")\n")
    config = Config(str(BASE_DIR / 'alembic.ini'))
    config.set_main_option('script_location', str(scripts))
    try:
        command.upgrade(config, 'head')
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT status,version FROM projects WHERE id='legacy'")).one() == ('preparing', 6)
            assert connection.execute(sa.text('SELECT version_num FROM alembic_version')).scalar() == 'test_following_data'
    finally:
        engine.dispose()


def test_versioned_early_chain_gets_all_missing_columns(alembic_config, monkeypatch, tmp_path):
    from app.db import Base
    engine = database(monkeypatch, tmp_path / 'early.db')
    try:
        command.upgrade(alembic_config, 'f7b3c8d2a901')
        with engine.begin() as connection:
            connection.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status) VALUES ('original','Original','2026-01-01','2026-12-31','archived')"))
        command.upgrade(alembic_config, 'head')
        with engine.connect() as connection:
            assert connection.execute(sa.text('SELECT status FROM projects')).scalar() == 'archived'
            assert compare_metadata(MigrationContext.configure(connection, opts={'compare_server_default': True}), Base.metadata) == []
    finally:
        engine.dispose()


def test_repeated_startup_has_no_schema_or_data_replay(client):
    from app.db import engine, init_db
    from unittest.mock import patch
    with engine.begin() as connection:
        connection.execute(sa.text('UPDATE tasks SET standard_hours=13 WHERE project_id IS NULL'))
        before = connection.execute(sa.text('SELECT id,standard_hours FROM tasks ORDER BY id')).all()
    before_schema = schema(engine)
    init_db()
    init_db()
    assert schema(engine) == before_schema
    with engine.connect() as connection:
        assert connection.execute(sa.text('SELECT id,standard_hours FROM tasks ORDER BY id')).all() == before


def test_missing_business_tables_with_version_marker_fail_loudly(alembic_config, monkeypatch, tmp_path):
    engine = database(monkeypatch, tmp_path / 'broken.db')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
        connection.execute(sa.text("INSERT INTO alembic_version VALUES ('d2e7f9a103b4')"))
    try:
        with pytest.raises(RuntimeError, match='业务表缺失'):
            command.upgrade(alembic_config, 'head')
    finally:
        engine.dispose()


def test_current_is_read_only_for_unversioned_database(alembic_config, monkeypatch, tmp_path):
    from migrations.v243_schema import metadata
    engine = database(monkeypatch, tmp_path / 'read-only.db')
    metadata.create_all(engine)
    before = schema(engine)
    try:
        command.current(alembic_config)
        assert 'alembic_version' not in sa.inspect(engine).get_table_names()
        assert schema(engine) == before
    finally:
        engine.dispose()


def test_upgrade_does_not_commit_callers_active_transaction(alembic_config, monkeypatch, tmp_path):
    engine = database(monkeypatch, tmp_path / 'caller-transaction.db')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE caller_writes (id INTEGER PRIMARY KEY)'))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(sa.text('INSERT INTO caller_writes VALUES (1)'))
            alembic_config.attributes['connection'] = connection
            try:
                with pytest.raises(RuntimeError, match='调用者已有的事务'):
                    command.upgrade(alembic_config, 'head')
            finally:
                alembic_config.attributes.pop('connection', None)
                transaction.rollback()
        with engine.connect() as connection:
            assert connection.execute(sa.text('SELECT count(*) FROM caller_writes')).scalar() == 0
    finally:
        engine.dispose()
