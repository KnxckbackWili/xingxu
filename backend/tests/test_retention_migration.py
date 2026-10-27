"""#85 frozen migration retains old archives and adopts old deleted live rows."""
import ast
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app import config
from app.db import engine, Base


def test_old_soft_deletions_enter_recycle_without_touching_old_archives(client, tmp_path):
    source = config.BASE_DIR / 'migrations/versions/g3a85b000001_retention_unification.py'
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or '').startswith('app') for node in ast.walk(ast.parse(source.read_text())))
    pg = engine.dialect.name == 'postgresql'
    schema = 'retention_' + uuid4().hex
    if pg:
        with engine.begin() as connection: connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_engine(config.DATABASE_URL, connect_args={'options': '-csearch_path=' + schema})
    else: isolated = create_engine('sqlite:///' + str(tmp_path / 'old.db'))
    cfg = Config(str(config.BASE_DIR / 'alembic.ini')); cfg.set_main_option('script_location', str(config.BASE_DIR / 'migrations'))
    def upgrade(revision):
        with isolated.connect() as connection:
            cfg.attributes['connection'] = connection; command.upgrade(cfg, revision)
    try:
        upgrade(ScriptDirectory.from_config(cfg).get_revision('g3a85b000001').down_revision)
        pid, aid = str(uuid4()), str(uuid4())
        with isolated.begin() as connection:
            connection.execute(text("INSERT INTO projects(id,name,status,version,deleted_at,start_date,end_date) VALUES(:id,'old deleted project','archived',4,'2025-01-01 00:00:00','2024-01-01','2024-12-31')"), {'id': pid})
            connection.execute(text("INSERT INTO project_archives(id,project_id,project_name,snapshot,change_logs,checksum,purged_at) VALUES(:id,'historical','unchanged archive','{}','[]','immutable-hash','2025-01-01 00:00:00')"), {'id': aid})
            old = connection.execute(text('SELECT * FROM project_archives')).all()
            project = connection.execute(text('SELECT * FROM projects')).all()
        upgrade('g3a85b000001'); upgrade('g3a85b000001')
        with isolated.connect() as connection:
            assert connection.execute(text('SELECT * FROM project_archives')).all() == old
            assert connection.execute(text('SELECT * FROM projects')).all() == project
            row = connection.execute(text('SELECT project_id,status_before_delete,backup_name,backup_bytes FROM project_deletion_records')).one()
            assert row == (pid, 'archived', '', 0)
            connection.execute(text('UPDATE project_deletion_records SET backup_bytes=:size'), {'size': 5 * 1024 ** 3})
            assert connection.execute(text('SELECT backup_bytes FROM project_deletion_records')).scalar_one() == 5 * 1024 ** 3
            connection.commit()
        # Preservation assertions above target #85 itself; compare the current
        # ORM only after applying the complete current chain in a fresh scope.
        upgrade('head')
        with isolated.connect() as connection:
            assert connection.execute(text('SELECT backup_bytes FROM project_deletion_records')).scalar_one() == 5 * 1024 ** 3
            assert compare_metadata(MigrationContext.configure(connection, opts={'compare_server_default': True}), Base.metadata) == []
    finally:
        isolated.dispose()
        if pg:
            with engine.begin() as connection: connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
