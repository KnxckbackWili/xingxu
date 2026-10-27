"""Named T24 increment preserves old issue facts without backfilling incidents."""
import ast,io,os,hashlib
from datetime import datetime,date
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.config import BASE_DIR
from app.db import Base


def cfg(output=None):
    result=Config(str(BASE_DIR/'alembic.ini'),output_buffer=output)
    result.set_main_option('script_location',str(BASE_DIR/'migrations'))
    return result


def named_range():
    script=ScriptDirectory.from_config(cfg())
    return script.get_revision('g3a24b000001').down_revision+':g3a24b000001'


@pytest.mark.parametrize('dialect',['sqlite','sqlite-offline','postgresql'])
def test_old_issue_fields_bytes_and_review_are_preserved_without_new_trigger(monkeypatch,tmp_path,dialect):
    source=BASE_DIR/'migrations/versions/g3a24b000001_triggered_documents.py'
    assert not any(isinstance(node,ast.ImportFrom) and (node.module or '').startswith('app') for node in ast.walk(ast.parse(source.read_text())))
    url='sqlite:///'+str(tmp_path/'prior.db') if dialect.startswith('sqlite') else os.getenv('T24_MIGRATION_TEST_URL')
    if not url:pytest.skip('isolated T24_MIGRATION_TEST_URL required')
    if dialect=='postgresql':assert sa.engine.make_url(url).database.startswith('agvm_v3_20261027_t24_migration')
    engine=sa.create_engine(url)
    if dialect=='postgresql':
        with engine.begin() as connection:
            connection.execute(sa.text('DROP SCHEMA public CASCADE'));connection.execute(sa.text('CREATE SCHEMA public'))
    monkeypatch.setattr('app.config.DATABASE_URL',url);monkeypatch.setenv('DATA_DIR',str(tmp_path))
    command.upgrade(cfg(),named_range().split(':')[0])
    content=b'original quality evidence\x00';path=tmp_path/'original.bin';path.write_bytes(content);digest=hashlib.sha256(content).hexdigest()
    with engine.begin() as connection:
        meta=sa.MetaData()
        def insert(table_name,**values):
            table=sa.Table(table_name,meta,autoload_with=connection,extend_existing=True);connection.execute(table.insert().values(**values))
        insert('users',id='u',username='original',password_hash='opaque',display_name='原报告人',role='pm')
        insert('projects',id='p',name='旧项目',manager='u',status='planning',start_date=date(2026,1,1),end_date=date(2026,12,31))
        insert('issues',id='i',project_id='p',title='原质量反馈',issue_type='hardware',created_at=datetime(2025,1,2,3,4,5),
            reporter_id='u',status='resolved',resolution='原处理结果',extra={'nature':'quality','feedback_date':'2024-05-08','nested':{'original':['A']}})
        insert('attachments',id='a',project_id='p',filename='原件.bin',stored_name='original.bin',file_size=len(content),
            content_type='application/octet-stream',uploaded_by='u',uploaded_at=datetime(2025,1,2,4),confidential=False,sha256=digest)
        previous={name:[dict(row) for row in connection.execute(sa.select(meta.tables[name])).mappings()] for name in ('issues','attachments')}
    if dialect=='sqlite-offline':
        output=io.StringIO();command.upgrade(cfg(output),named_range(),sql=True)
        with engine.connect() as connection:
            raw=connection.connection.driver_connection
            raw.execute('PRAGMA foreign_keys=ON');connection.commit()
            import sqlite3
            script=output.getvalue()
            broken=script.replace('CREATE TABLE document_trigger_events','INVALID SQL; CREATE TABLE document_trigger_events',1)
            try:
                with pytest.raises(sqlite3.Error):raw.executescript(broken)
            finally:
                raw.rollback();raw.execute('PRAGMA foreign_keys=ON')
            assert raw.execute('SELECT count(*) FROM issues').fetchone()[0]==1
            assert 'nature' not in {row[1] for row in raw.execute('PRAGMA table_info(issues)')}
            raw.executescript(script)
            assert raw.execute('PRAGMA foreign_keys').fetchone()[0]==1
            assert raw.execute('PRAGMA foreign_key_check').fetchall()==[]
    else:command.upgrade(cfg(),'g3a24b000001')
    with engine.connect() as connection:
        meta=sa.MetaData()
        for name,rows in previous.items():
            table=sa.Table(name,meta,autoload_with=connection)
            current=list(connection.execute(sa.select(table)).mappings())
            assert len(current)==len(rows)
            assert [{key:item[key] for key in rows[0]} for item in current]==rows
        assert connection.execute(sa.text("SELECT nature FROM issues WHERE id='i'")).scalar_one()=='normal'
        assert connection.execute(sa.text('SELECT count(*) FROM document_trigger_events')).scalar_one()==0
        assert connection.execute(sa.text('SELECT count(*) FROM issue_sla_receipts')).scalar_one()==0
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    command.upgrade(cfg(),'head')
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection,opts={'compare_server_default':True}),Base.metadata)==[]
    engine.dispose()


@pytest.mark.parametrize('url',['sqlite:///offline.db','postgresql://offline/unused'])
def test_named_increment_compiles_without_live_orm(monkeypatch,url):
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    output=io.StringIO();command.upgrade(cfg(output),named_range(),sql=True)
    assert 'CREATE TABLE document_trigger_events' in output.getvalue()
    assert 'g3a24b000001' in output.getvalue()
