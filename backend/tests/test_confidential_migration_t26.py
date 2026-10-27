"""Real g24→g26 upgrade preserves facts and never fabricates historical grants."""
from contextlib import contextmanager
import io
from uuid import uuid4
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app import config, models
from app.db import Base


@contextmanager
def migration_database(tmp_path):
    base=make_url(config.DATABASE_URL)
    if base.get_backend_name()=='sqlite':
        yield 'sqlite:///'+str(tmp_path/'confidential-migration.db')
        return
    name='agvm_t26_migration_'+uuid4().hex[:16]
    admin=sa.create_engine(base.set(database='postgres'),isolation_level='AUTOCOMMIT')
    with admin.connect() as connection:connection.execute(sa.text('CREATE DATABASE '+name))
    try:yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:connection.execute(sa.text('DROP DATABASE '+name))
        admin.dispose()


def test_forward_migration_retains_facts_and_defaults_private_codes_without_implicit_grants(monkeypatch,tmp_path):
    with migration_database(tmp_path) as url:
        monkeypatch.setattr(config,'DATABASE_URL',url)
        cfg=Config(str(config.BASE_DIR/'alembic.ini'));cfg.set_main_option('script_location',str(config.BASE_DIR/'migrations'))
        command.upgrade(cfg,'g3a32b000001')
        engine=sa.create_engine(url)
        try:
            meta=sa.MetaData();meta.reflect(engine)
            uid,pid,definition,doc,standalone,derived,version=[str(uuid4()) for _ in range(7)]
            rule={'stage_key':'6','code':'6.11.6a','name':'原IP位置说明','required':True,'scope':'project','timing_type':'on_demand','sort_order':0}
            with engine.begin() as c:
                c.execute(meta.tables['users'].insert().values(id=uid,username='frozen-owner',display_name='原负责人',password_hash='test-only',role='pm'))
                from datetime import date
                c.execute(meta.tables['projects'].insert().values(id=pid,name='原有项目',manager=uid,start_date=date(2026,1,1),end_date=date(2026,12,31),status='preparing'))
                c.execute(meta.tables['project_document_definitions'].insert().values(id=definition,project_id=pid,source_key='test:retained',
                    confidential_default=False,external_visible_default=False,external_never_visible=False,**rule))
                c.execute(meta.tables['project_documents'].insert().values(id=doc,project_id=pid,definition_id=definition,instance_key='test:retained',
                    due_is_estimated=False,status='submitted',confidential=False,external_visible=False,external_never_visible=False,version=4,**rule))
                for identity in (standalone,derived):
                    c.execute(meta.tables['attachments'].insert().values(id=identity,project_id=pid,filename='original.txt',stored_name=identity,
                        file_size=123,sha256='a'*64,confidential=True,uploaded_by=uid))
                c.execute(meta.tables['document_versions'].insert().values(id=version,project_document_id=doc,attachment_id=derived,uploaded_by=uid,note='原版本说明'))
                users_before=c.execute(sa.text('SELECT * FROM users')).all();project_before=c.execute(sa.text('SELECT * FROM projects')).all()
            command.upgrade(cfg,'head')
            command.upgrade(cfg,'head')
            with engine.connect() as c:
                assert c.execute(sa.text('SELECT * FROM users')).all()==users_before
                assert c.execute(sa.text('SELECT * FROM projects')).all()==project_before
                result=c.execute(sa.text('SELECT confidential,status,version,confidential_user_ids FROM project_documents WHERE id=:id'),{'id':doc}).one()
                assert result[0] and result[1:3]==('submitted',4)
                assert result[3] in ([], '[]')
                assert c.execute(sa.text('SELECT confidential_default FROM project_document_definitions WHERE id=:id'),{'id':definition}).scalar()
                assert c.execute(sa.text('SELECT confidential_user_ids FROM attachments WHERE id=:id'),{'id':standalone}).scalar() in ([], '[]')
                assert c.execute(sa.text('SELECT filename,file_size,sha256 FROM attachments WHERE id=:id'),{'id':derived}).one()==('original.txt',123,'a'*64)
                assert c.execute(sa.text('SELECT note FROM document_versions WHERE id=:id'),{'id':version}).scalar()=='原版本说明'
                assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
                if engine.dialect.name=='sqlite':assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
            output=io.StringIO();offline=Config(str(config.BASE_DIR/'alembic.ini'),output_buffer=output)
            offline.set_main_option('script_location',str(config.BASE_DIR/'migrations'))
            command.upgrade(offline,'g3a32b000001:g3a26b000001',sql=True)
            assert 'confidential_user_ids' in output.getvalue() and 'g3a26b000001' in output.getvalue()
        finally:engine.dispose()
