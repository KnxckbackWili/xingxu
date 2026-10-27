"""Upgrade legacy planned dates without inventing historical actual instants."""
import json

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import BASE_DIR


def test_legacy_dates_survive_upgrade_and_repeated_start(monkeypatch, tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'legacy.db')
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    cfg = Config(str(BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BASE_DIR / 'migrations'))
    command.upgrade(cfg, 'g3a03b000001')
    engine = sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,planned_entry_date,entry_plan) VALUES ('legacy','原项目','2026-01-01','2026-12-31','executing','2026-10-01',:entry)"),
                  {'entry': json.dumps({'entry_date': '2026-10-03', 'meeting_point': '东门'})})
        before = c.execute(sa.text('SELECT name,status,planned_entry_date,entry_plan FROM projects')).all()
    command.upgrade(cfg, 'head')
    command.upgrade(cfg, 'head')
    with engine.connect() as c:
        assert c.execute(sa.text('SELECT name,status,planned_entry_date,entry_plan FROM projects')).all() == before
        assert c.execute(sa.text('SELECT event_key,planned_date,actual_at,recorded_by FROM project_events ORDER BY event_key')).all() == [
            ('arrival_all', '2026-10-03', None, None), ('ship', '2026-10-01', None, None)]
        assert c.execute(sa.text('SELECT dispatch_platform FROM projects')).scalar() is None
        assert c.execute(sa.text('PRAGMA foreign_key_check')).all() == []
    graph = ScriptDirectory.from_config(cfg)
    assert len(graph.get_heads()) == 1
    assert 'g3a20b000001' in {revision.revision for revision in graph.walk_revisions()}
    engine.dispose()


def test_bad_legacy_date_aborts_without_partial_schema_or_data(monkeypatch, tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'bad.db')
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    cfg = Config(str(BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BASE_DIR / 'migrations'))
    command.upgrade(cfg, 'g3a03b000001')
    engine = sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,entry_plan) VALUES ('bad','原项目','2026-01-01','2026-12-31','draft',:entry)"),
                  {'entry': json.dumps({'entry_date': '未确定'})})
    with pytest.raises(RuntimeError, match='迁移不猜测'):
        command.upgrade(cfg, 'head')
    with engine.connect() as c:
        assert c.execute(sa.text('SELECT version_num FROM alembic_version')).scalar() == 'g3a03b000001'
        assert 'project_events' not in sa.inspect(c).get_table_names()
        assert 'dispatch_platform' not in {x['name'] for x in sa.inspect(c).get_columns('projects')}
        assert json.loads(c.execute(sa.text('SELECT entry_plan FROM projects')).scalar())['entry_date'] == '未确定'
    engine.dispose()
