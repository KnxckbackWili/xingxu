"""Frozen g22→g23 preserves every evidence row and supports both SQL dialects."""
import hashlib
import io
import os
from datetime import date, datetime

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.config import BASE_DIR
from app.db import Base


def configuration(buffer=None):
    config=Config(str(BASE_DIR/'alembic.ini'),output_buffer=buffer)
    config.set_main_option('script_location',str(BASE_DIR/'migrations'))
    return config


def increment_range(config):
    parent=ScriptDirectory.from_config(config).get_revision('g3a23b000001').down_revision
    return f'{parent}:g3a23b000001'


@pytest.mark.parametrize('dialect',['sqlite','sqlite-offline','postgresql'])
def test_existing_document_versions_and_source_bytes_survive(monkeypatch,tmp_path,dialect):
    url='sqlite:///'+str(tmp_path/'g22.db') if dialect.startswith('sqlite') else os.getenv('T23_MIGRATION_TEST_URL')
    if not url:pytest.skip('T23_MIGRATION_TEST_URL must name an isolated PG migration database')
    engine=sa.create_engine(url)
    if dialect=='postgresql':
        assert sa.engine.make_url(url).database.startswith('agvm_v3_20261027_t23_migration')
        with engine.begin() as connection:
            connection.execute(sa.text('DROP SCHEMA public CASCADE'));connection.execute(sa.text('CREATE SCHEMA public'))
    monkeypatch.setenv('DATA_DIR',str(tmp_path));monkeypatch.setattr('app.config.DATABASE_URL',url)
    config=configuration();command.upgrade(config,increment_range(config).split(':')[0])
    uploads=tmp_path/'uploads';uploads.mkdir()
    raw=b'original signed evidence\x00';source=uploads/'original.bin';source.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest();now=datetime(2026,10,27,12)
    second=uploads/'second.bin';second.write_bytes(b'second immutable original')
    original_hashes={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in (source,second)}
    with engine.begin() as connection:
        metadata=sa.MetaData()
        def insert(table,**values):
            row=sa.Table(table,metadata,autoload_with=connection,extend_existing=True)
            connection.execute(row.insert().values(**values))
        insert('users',id='u',username='original',password_hash='opaque',display_name='原提交人',role='pm')
        insert('projects',id='p',name='旧项目',start_date=date(2026,1,1),end_date=date(2026,12,31),manager='u',status='planning')
        rule={'stage_key':'6','code':'6.1','name':'原点检','required':True,'scope':'project','timing_type':'on_demand',
              'sort_order':0,'source_metadata':{'original':'原来源'}}
        insert('project_document_definitions',id='r',project_id='p',source_key='original:r',created_by='u',created_at=now,
               confidential_default=False,external_visible_default=False,external_never_visible=False,**rule)
        insert('project_documents',id='d',project_id='p',definition_id='r',instance_key='r:-:-:-',due_at=now,
               due_is_estimated=False,status='submitted',confidential=False,external_visible=False,external_never_visible=False,
               submitted_at=now,submitted_by='u',version=4,created_at=now,**rule)
        insert('attachments',id='a',project_id='p',filename='原件.bin',stored_name='original.bin',file_size=len(raw),
               content_type='application/octet-stream',uploaded_by='u',uploaded_at=now,confidential=False,sha256=digest)
        insert('document_versions',id='v',project_document_id='d',attachment_id='a',uploaded_by='u',uploaded_at=now,
               note='原版本',review_metadata={'latest_review':{'by':'original-reviewer','decision':'approved'}})
        insert('attachments',id='a2',project_id='p',filename='另一原件.bin',stored_name='second.bin',file_size=second.stat().st_size,
               content_type='application/octet-stream',uploaded_by='u',uploaded_at=now,confidential=False,sha256=original_hashes['second.bin'])
        insert('document_versions',id='v2',project_document_id='d',attachment_id='a2',uploaded_by='u',uploaded_at=now,
               note='另一保留原版本',review_metadata={'original':'原审核资料'})
        before={name:[dict(row) for row in connection.execute(sa.select(metadata.tables[name])).mappings()]
                for name in ('project_document_definitions','project_documents','document_versions','attachments')}
    if dialect.startswith('sqlite'):
        with engine.connect() as connection:
            raw_connection=connection.connection.driver_connection
            raw_connection.execute('PRAGMA foreign_keys=ON');connection.commit()
            config.attributes['connection']=connection
            if dialect=='sqlite-offline':
                import sqlite3
                output=io.StringIO();command.upgrade(configuration(output),increment_range(configuration()),sql=True)
                script=output.getvalue()
                broken=script.replace('CREATE TABLE document_notice_receipts','INVALID SQL FOR ROLLBACK; CREATE TABLE document_notice_receipts',1)
                try:
                    with pytest.raises(sqlite3.Error):raw_connection.executescript(broken)
                finally:
                    raw_connection.rollback();raw_connection.execute('PRAGMA foreign_keys=ON')
                assert raw_connection.execute('SELECT count(*) FROM document_versions').fetchone()[0]==2
                assert 'owner_id' not in {row[1] for row in raw_connection.execute('PRAGMA table_info(project_documents)')}
                raw_connection.executescript(script)
            else:
                def fail(connection,cursor,statement,parameters,context,executemany):
                    if 'CREATE TABLE document_notice_receipts' in statement:raise RuntimeError('injected migration failure')
                sa.event.listen(connection,'before_cursor_execute',fail)
                try:
                    with pytest.raises(RuntimeError,match='injected migration failure'):command.upgrade(config,'head')
                finally:sa.event.remove(connection,'before_cursor_execute',fail)
                assert connection.exec_driver_sql('SELECT count(*) FROM document_versions').scalar()==2
                connection.commit()
                assert 'owner_id' not in {row['name'] for row in sa.inspect(connection).get_columns('project_documents')}
                connection.commit();command.upgrade(config,'head')
            assert raw_connection.execute('PRAGMA foreign_keys').fetchone()[0]==1
            connection.commit();command.upgrade(config,'head')
            config.attributes.pop('connection')
    else:
        command.upgrade(config,'head');command.upgrade(config,'head')
    with engine.connect() as connection:
        if dialect.startswith('sqlite'):
            connection.exec_driver_sql('PRAGMA foreign_keys=ON');connection.commit()
        metadata=sa.MetaData()
        for name,originals in before.items():
            table=sa.Table(name,metadata,autoload_with=connection)
            rows=list(connection.execute(sa.select(table)).mappings())
            assert len(rows)==len(originals)
            for original,current in zip(originals,rows):assert dict(original)=={key:current[key] for key in original}
        assert compare_metadata(MigrationContext.configure(connection,opts={'compare_server_default':True}),Base.metadata)==[]
        if dialect.startswith('sqlite'):assert connection.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
        assert connection.execute(sa.text('SELECT count(*) FROM document_notice_receipts')).scalar()==0
        assert connection.execute(sa.text('SELECT count(*) FROM project_report_receipts')).scalar()==0
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():connection.execute(sa.text("DELETE FROM attachments WHERE id='a'"))
        assert connection.execute(sa.text('SELECT count(*) FROM document_versions')).scalar()==2
    assert {file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in (source,second)}==original_hashes
    engine.dispose()


@pytest.mark.parametrize('url',['sqlite:///offline.db','postgresql+psycopg2://test@localhost/offline'])
def test_t23_offline_sql_is_frozen_additive_schema(monkeypatch,url):
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    output=io.StringIO();command.upgrade(configuration(output),increment_range(configuration()),sql=True)
    sql=output.getvalue()
    assert 'owner_id' in sql and 'CREATE TABLE document_notice_receipts' in sql
    assert 'CREATE TABLE project_report_receipts' in sql and 'ADD COLUMN due_basis' in sql
    assert 'DELETE FROM document_versions' not in sql
