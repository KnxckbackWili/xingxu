"""Frozen T25 increment keeps old evidence and supports true 64-bit sizes."""
import ast,io,hashlib
from uuid import uuid4
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,text
from app import config
from app.db import engine,Base
import pytest


@pytest.mark.parametrize('offline',[False,True])
def test_named_storage_increment_preserves_bytes_rows_fks_and_64_bit_sizes(client,tmp_path,offline):
    source=config.BASE_DIR/'migrations/versions/g3a25b000001_resumable_storage.py'
    assert not any(isinstance(node,ast.ImportFrom) and (node.module or '').startswith('app') for node in ast.walk(ast.parse(source.read_text())))
    pg=engine.dialect.name=='postgresql';schema='storage_'+uuid4().hex
    if pg:
        with engine.begin() as connection:connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated=create_engine(config.DATABASE_URL,connect_args={'options':'-csearch_path='+schema})
    else:isolated=create_engine('sqlite:///'+str(tmp_path/'storage.db'))
    cfg=Config(str(config.BASE_DIR/'alembic.ini'));cfg.set_main_option('script_location',str(config.BASE_DIR/'migrations'))
    parent=ScriptDirectory.from_config(cfg).get_revision('g3a25b000001').down_revision
    def upgrade(revision):
        with isolated.connect() as connection:
            if not pg:connection.exec_driver_sql('PRAGMA foreign_keys=ON');connection.commit()
            cfg.attributes['connection']=connection;command.upgrade(cfg,revision)
    pid,did,aid,vid=[str(uuid4()) for _ in range(4)];original=b'old immutable original';path=tmp_path/'original';path.write_bytes(original)
    try:
        upgrade(parent)
        with isolated.begin() as connection:
            connection.execute(text("INSERT INTO projects(id,name,status,version,start_date,end_date) VALUES(:id,'T25 source','preparing',1,'2026-01-01','2026-12-31')"),{'id':pid})
            connection.execute(text("INSERT INTO attachments(id,project_id,filename,stored_name,file_size,sha256) VALUES(:id,:pid,'source.bin','old-original',:size,:sha)"),{'id':aid,'pid':pid,'size':len(original),'sha':hashlib.sha256(original).hexdigest()})
            connection.execute(text("INSERT INTO project_documents(id,project_id,instance_key,stage_key,code,name,required,scope,timing_type,sort_order,status,version,confidential,external_visible,external_never_visible,due_is_estimated) VALUES(:id,:pid,'old','5','5.1','old',true,'project','on_demand',0,'submitted',1,false,false,false,false)"),{'id':did,'pid':pid})
            connection.execute(text('INSERT INTO document_versions(id,project_document_id,attachment_id) VALUES(:id,:did,:aid)'),{'id':vid,'did':did,'aid':aid})
            old={table:connection.execute(text('SELECT * FROM '+table)).all() for table in ('attachments','document_versions','project_documents')}
        if offline:
            output=io.StringIO();cfg.output_buffer=output
            with isolated.connect() as connection:
                cfg.attributes['connection']=connection;command.upgrade(cfg,parent+':g3a25b000001',sql=True)
            sql=output.getvalue()
            assert 'CREATE TABLE upload_sessions' in sql
            if pg:
                assert 'BIGINT' in sql
                with isolated.begin() as connection:connection.exec_driver_sql(sql)
            else:
                with isolated.connect() as connection:
                    connection.exec_driver_sql('PRAGMA foreign_keys=ON')
                    connection.connection.driver_connection.executescript(sql)
                    assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar()==1
        else:upgrade('g3a25b000001')
        with isolated.begin() as connection:
            assert all(connection.execute(text('SELECT * FROM '+table)).all()==rows for table,rows in old.items())
            assert path.read_bytes()==original and hashlib.sha256(path.read_bytes()).hexdigest()==hashlib.sha256(original).hexdigest()
            connection.execute(text('UPDATE attachments SET file_size=:size WHERE id=:id'),{'size':2147483648,'id':aid})
            assert connection.execute(text('SELECT file_size FROM attachments WHERE id=:id'),{'id':aid}).scalar_one()==2147483648
        # The original version still restricts deletion of its source file.
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            with isolated.begin() as connection:
                if not pg:connection.exec_driver_sql('PRAGMA foreign_keys=ON')
                connection.execute(text('DELETE FROM attachments WHERE id=:id'),{'id':aid})
        upgrade('head')
        with isolated.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection,opts={'compare_server_default':True}),Base.metadata)==[]
    finally:
        isolated.dispose()
        if pg:
            with engine.begin() as connection:connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
