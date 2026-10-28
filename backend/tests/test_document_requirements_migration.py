"""Existing templates receive the new definitions once, without touching old work."""
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.config import BASE_DIR
from app.db import Base


def test_t20_templates_upgrade_once_and_keep_custom_tree(monkeypatch, tmp_path):
    url = 'sqlite:///' + str(tmp_path / 't20.db')
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    cfg = Config(str(BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BASE_DIR / 'migrations'))
    command.upgrade(cfg, 'g3a20b000001')
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO templates (id,name,description,is_system) VALUES ('custom','客户专用','原自定义说明',0)"))
        connection.execute(sa.text("INSERT INTO phases (id,name,template_id,sort_order) VALUES ('phase','原有自定义阶段','custom',3)"))
        before = connection.execute(sa.text('SELECT id,project_id,template_id,name,sort_order,color,entry_criteria,exit_criteria FROM phases')).all()
        old_names = connection.execute(sa.text("SELECT name FROM template_preparation_items WHERE template_id IS NULL AND category != 'procurement'")).scalars().all()
    command.upgrade(cfg, 'head')
    with engine.begin() as connection:
        assert connection.execute(sa.text('SELECT id,project_id,template_id,name,sort_order,color,entry_criteria,exit_criteria FROM phases')).all() == before
        assert connection.execute(sa.text("SELECT count(*) FROM document_requirements WHERE template_id IS NULL AND stage_key!='legacy'")).scalar() == 56
        assert connection.execute(sa.text("SELECT count(*) FROM document_requirements WHERE template_id='custom'")).scalar() == 56
        assert sorted(connection.execute(sa.text("SELECT name FROM document_requirements WHERE template_id IS NULL AND stage_key='legacy'")).scalars()) == sorted(old_names)
        connection.execute(sa.text("DELETE FROM document_requirements WHERE template_id='custom' AND code='4.1'"))
    command.upgrade(cfg, 'head')
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM document_requirements WHERE template_id='custom'")).scalar() == 55
        assert compare_metadata(MigrationContext.configure(connection, opts={'compare_server_default': True}), Base.metadata) == []
        assert connection.execute(sa.text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()
