"""Former ready projects become preparing with provenance and an audit row, on SQLite and PostgreSQL."""
import ast
import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app import config
from app.db import engine


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def test_ready_projects_merge_into_preparing_with_provenance(client, tmp_path, monkeypatch):
    source = config.BASE_DIR / 'migrations/versions/g3a90b000001_merge_ready_into_preparing.py'
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or '').startswith('app')
                   for node in ast.walk(ast.parse(source.read_text())))
    url = make_url(config.DATABASE_URL)
    pg = url.drivername.startswith('postgresql')
    schema = 'merge_ready_' + uuid4().hex
    if pg:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_engine(url, connect_args={'options': '-csearch_path=' + schema})
    else:
        url = make_url('sqlite:///' + str(tmp_path / 'pre-merge-ready.db'))
        isolated = create_engine(url)
    cfg = Config(str(config.BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(config.BASE_DIR / 'migrations'))
    monkeypatch.setattr(config, 'DATABASE_URL', str(url))

    def upgrade(revision):
        with isolated.connect() as connection:
            cfg.attributes['connection'] = connection
            command.upgrade(cfg, revision)

    try:
        upgrade('g3a30b000002')
        insert = text('INSERT INTO projects(id,name,start_date,end_date,status,suspension,legacy_lifecycle,version) '
                      'VALUES (:id,:name,:start,:end,:status,:suspension,:legacy,:version)')
        rows = [
            ('ready-1', 'ready', {}, {'original_status': 'planning', 'migration': 'g3a28b000001'}),
            ('paused-1', 'suspended', {'status_before': 'ready', 'reason': '客户暂停'}, None),
            ('paused-2', 'suspended', {'status_before': 'executing', 'reason': '停电'}, None),
            ('prep-1', 'preparing', {}, None),
            ('exec-1', 'executing', {}, None),
        ]
        with isolated.begin() as connection:
            for pid, status, suspension, legacy in rows:
                connection.execute(insert, {'id': pid, 'name': pid, 'start': '2026-10-01', 'end': '2026-12-31', 'status': status,
                    'suspension': json.dumps(suspension), 'legacy': json.dumps(legacy) if legacy else None, 'version': 3})
        upgrade('head')
        upgrade('head')
        with isolated.connect() as connection:
            projects = {row[0]: row[1:] for row in connection.execute(text(
                'SELECT id,status,suspension,legacy_lifecycle,version FROM projects'))}
            assert projects['ready-1'][0] == 'preparing' and projects['ready-1'][3] == 4
            legacy = _json(projects['ready-1'][2])
            assert legacy['original_status'] == 'planning'  # earlier provenance kept
            assert legacy['ready_merge'] == {'migration': 'g3a90b000001', 'original_status': 'ready', 'original_status_before': None}
            assert projects['paused-1'][0] == 'suspended'
            assert _json(projects['paused-1'][1]) == {'status_before': 'preparing', 'reason': '客户暂停'}
            assert _json(projects['paused-1'][2])['ready_merge']['original_status_before'] == 'ready'
            for untouched in ('paused-2', 'prep-1', 'exec-1'):
                assert projects[untouched][3] == 3 and projects[untouched][2] is None
            logs = connection.execute(text("SELECT project_id,detail,old_value,new_value FROM change_logs "
                                           "WHERE entity_type='project' AND detail LIKE '阶段合并%'")).all()
            assert sorted(row[0] for row in logs) == ['paused-1', 'ready-1']
            by_project = {row[0]: row for row in logs}
            assert _json(by_project['ready-1'][2])['status'] == 'ready' and _json(by_project['ready-1'][3])['status'] == 'preparing'
            summary = connection.execute(text("SELECT detail FROM change_logs WHERE entity_type='migration' AND entity_id='g3a90b000001'")).all()
            assert len(summary) == 1 and json.loads(summary[0][0]) == {'changed_projects': 2}
        with pytest.raises(IntegrityError), isolated.begin() as connection:
            connection.execute(text("UPDATE projects SET status='ready' WHERE id='prep-1'"))
    finally:
        isolated.dispose()
        if pg:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
