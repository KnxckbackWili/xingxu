"""Frozen g26→g53, data preservation, metadata and offline SQL on each dialect."""
from contextlib import contextmanager
from uuid import uuid4
import io
from datetime import date
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app import config,models
from app.db import Base


@contextmanager
def database(tmp_path):
    base=make_url(config.DATABASE_URL)
    if base.get_backend_name()=='sqlite':
        yield 'sqlite:///'+str(tmp_path/'external-migration.db');return
    name='agvm_t53_migration_'+uuid4().hex[:16]
    admin=sa.create_engine(base.set(database='postgres'),isolation_level='AUTOCOMMIT')
    with admin.connect() as c:c.execute(sa.text('CREATE DATABASE '+name))
    try:yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:c.execute(sa.text('DROP DATABASE '+name))
        admin.dispose()


def test_single_forward_head_preserves_business_rows_and_has_no_raw_token_column(monkeypatch,tmp_path):
    with database(tmp_path) as url:
        monkeypatch.setattr(config,'DATABASE_URL',url)
        cfg=Config(str(config.BASE_DIR/'alembic.ini'));cfg.set_main_option('script_location',str(config.BASE_DIR/'migrations'))
        command.upgrade(cfg,'g3a25b000001')
        engine=sa.create_engine(url)
        try:
            meta=sa.MetaData();meta.reflect(engine)
            uid,pid=str(uuid4()),str(uuid4())
            with engine.begin() as c:
                c.execute(meta.tables['users'].insert().values(id=uid,username='retained-owner',display_name='原负责人',password_hash='test-only',role='pm'))
                c.execute(meta.tables['projects'].insert().values(id=pid,name='原有项目',manager=uid,status='preparing',start_date=date(2026,1,1),end_date=date(2026,12,31)))
                users=c.execute(sa.text('SELECT * FROM users')).all();projects=c.execute(sa.text('SELECT * FROM projects')).all()
            command.upgrade(cfg,'head');command.upgrade(cfg,'head')
            with engine.connect() as c:
                assert c.execute(sa.text('SELECT * FROM users')).all()==users
                assert c.execute(sa.text('SELECT * FROM projects')).all()==projects
                assert c.execute(sa.text('SELECT count(*) FROM external_shares')).scalar()==0
                assert c.execute(sa.text('SELECT count(*) FROM external_access_logs')).scalar()==0
                assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
            assert 'token' not in {column['name'] for column in sa.inspect(engine).get_columns('external_shares')}
            assert ScriptDirectory.from_config(cfg).get_heads()==['g3a53b000001']
            output=io.StringIO();offline=Config(str(config.BASE_DIR/'alembic.ini'),output_buffer=output)
            offline.set_main_option('script_location',str(config.BASE_DIR/'migrations'))
            command.upgrade(offline,'g3a25b000001:g3a53b000001',sql=True)
            assert 'external_access_logs' in output.getvalue() and 'token_hash' in output.getvalue()
        finally:engine.dispose()
