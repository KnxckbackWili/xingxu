"""Whole-table compatibility and the actual Alembic graph, no live database."""
from pathlib import Path
import importlib.util
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from app.db import Base
from app.models import ProjectDeletionRecord
from migrations.v243_schema import ProjectEditHistory


def test_single_head_follows_system_permissions_and_has_postgresql_cascade_ddl():
    backend = Path(__file__).parents[1]
    config = Config(str(backend / 'alembic.ini'))
    config.set_main_option('script_location', str(backend / 'migrations'))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    assert 'd2e7f9a103b4' in {revision.revision for revision in scripts.walk_revisions()}
    assert scripts.get_revision('d2e7f9a103b4').down_revision == 'b6d4e8f103a2'
    for model in (ProjectDeletionRecord, ProjectEditHistory):
        ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert 'ON DELETE CASCADE' in ddl and 'JSON' in ddl


def test_incremental_migration_preserves_old_rows_and_repeated_create_all():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as db:
        db.exec_driver_sql('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, display_name TEXT)')
        db.exec_driver_sql('CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, name TEXT, version INTEGER)')
        db.exec_driver_sql("INSERT INTO users VALUES ('u', '原用户')")
        db.exec_driver_sql("INSERT INTO projects VALUES ('p', '原项目', 7)")
        before = db.exec_driver_sql('SELECT * FROM projects').fetchall()
        path = Path(__file__).parents[1] / 'migrations/versions/d2e7f9a103b4_add_project_recovery_history.py'
        spec = importlib.util.spec_from_file_location('recovery_migration_test', path)
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
            migration.upgrade()
        assert db.exec_driver_sql('SELECT * FROM projects').fetchall() == before
        assert {'project_deletion_records', 'project_edit_history'} <= set(inspect(db).get_table_names())
        assert len(inspect(db).get_columns('project_edit_history')) == 13
        assert inspect(db).get_unique_constraints('project_edit_history')[0]['column_names'] == ['project_id', 'save_version']


def test_offline_postgresql_upgrade_emits_both_tables_and_no_old_alter():
    import io
    backend = Path(__file__).parents[1]
    path = backend / 'migrations/versions/d2e7f9a103b4_add_project_recovery_history.py'
    spec = importlib.util.spec_from_file_location('recovery_migration_offline', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': buffer})
    with Operations.context(context):
        migration.upgrade()
    sql = buffer.getvalue()
    assert 'CREATE TABLE project_deletion_records' in sql
    assert 'CREATE TABLE project_edit_history' in sql
    assert 'ALTER TABLE projects' not in sql and 'ALTER TABLE users' not in sql
    assert 'CREATE INDEX ix_project_edit_history_chain_id' in sql
