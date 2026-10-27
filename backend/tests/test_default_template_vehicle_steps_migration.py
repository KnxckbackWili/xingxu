"""T30 default-template step binding: existing rows, edited rows and the audit row, on SQLite and PostgreSQL."""
import ast
import json
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import config
from app.db import engine


def test_binds_only_untouched_default_and_preset_rows_with_audit(client, tmp_path, monkeypatch):
    source = config.BASE_DIR / 'migrations/versions/g3a30b000002_default_template_vehicle_steps.py'
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or '').startswith('app')
                   for node in ast.walk(ast.parse(source.read_text())))
    url = make_url(config.DATABASE_URL)
    pg = url.drivername.startswith('postgresql')
    schema = 't30_steps_' + uuid4().hex
    if pg:
        # Real column lengths matter here (SQLite ignores VARCHAR limits).
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    else:
        url = make_url('sqlite:///' + str(tmp_path / 'pre-t30-steps.db'))
        isolated = create_engine(url)
    cfg = Config(str(config.BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(config.BASE_DIR / 'migrations'))
    monkeypatch.setattr(config, 'DATABASE_URL', str(url))

    def upgrade(revision):
        with isolated.connect() as connection:
            cfg.attributes['connection'] = connection
            command.upgrade(cfg, revision)

    try:
        upgrade('g3a40b000002')
        with isolated.begin() as connection:
            insert = text('INSERT INTO tasks(id,template_id,project_id,name,quantity_type,vehicle_step_key) '
                          'VALUES (:id,:template,NULL,:name,:qtype,:key)')
            connection.execute(insert, {'id': 'task-005', 'template': None, 'name': '开箱检查', 'qtype': 'per_vehicle', 'key': None})
            connection.execute(insert, {'id': 'task-009', 'template': None, 'name': '单车机械与导航调试', 'qtype': 'per_vehicle', 'key': None})
            # Renamed by an admin: not the seeded identity any more.
            connection.execute(insert, {'id': 'task-012', 'template': None, 'name': '现场改名的载荷测试', 'qtype': 'per_vehicle', 'key': None})
            # Already bound by hand: kept.
            connection.execute(insert, {'id': 'task-022', 'template': None, 'name': '多车联调', 'qtype': 'per_vehicle', 'key': 'go_live'})
            connection.execute(text("INSERT INTO templates(id,name) VALUES ('preset-1','标准 AGV 实施模板'),('preset-2','叉车重载项目模板')"))
            connection.execute(insert, {'id': 'copy-1', 'template': 'preset-1', 'name': '开箱检查', 'qtype': 'per_vehicle', 'key': None})
            connection.execute(insert, {'id': 'copy-2', 'template': 'preset-2', 'name': '开箱检查', 'qtype': 'per_vehicle', 'key': None})
            # preset-2 was edited after seeding: its copies stay as they are.
            connection.execute(text("INSERT INTO change_logs(id,entity_type,entity_id,action,detail) "
                                    "VALUES ('edit-1','template','preset-2','update','管理员修改模板')"))
        upgrade('head')
        upgrade('head')
        with isolated.connect() as connection:
            keys = dict(connection.execute(text('SELECT id,vehicle_step_key FROM tasks')).all())
            assert keys == {'task-005': 'arrival_inspection', 'task-009': 'single_commissioning', 'task-012': None,
                            'task-022': 'go_live', 'copy-1': 'arrival_inspection', 'copy-2': None}
            audits = connection.execute(text("SELECT action,old_value,new_value FROM change_logs "
                                             "WHERE entity_type='migration' AND entity_id='g3a30b000002'")).all()
            assert len(audits) == 1
            action, old, new = audits[0]
            old = json.loads(old) if isinstance(old, str) else old
            new = json.loads(new) if isinstance(new, str) else new
            assert action == 'bind_vehicle_steps'
            assert {row['task_id'] for row in new['tasks']} == {'task-005', 'task-009', 'copy-1'}
            assert all(row['vehicle_step_key'] is None for row in old['tasks'])
    finally:
        isolated.dispose()
        if pg:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
