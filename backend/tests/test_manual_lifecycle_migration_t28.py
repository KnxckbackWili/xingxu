"""Actual old schema rows migrate without guessing timestamps or losing provenance."""
import hashlib
import json
from uuid import uuid4
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from app import config
from app.db import engine, Base


def test_old_states_audit_milestones_suspensions_and_files_survive_atomic_migration(client,tmp_path):
    pg=engine.dialect.name=='postgresql';schema='lifecycle_'+uuid4().hex
    if pg:
        with engine.begin() as c:c.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated=create_engine(config.DATABASE_URL,connect_args={'options':'-csearch_path='+schema})
    else:
        isolated=create_engine('sqlite:///'+str(tmp_path/'old-status.db'))
        with isolated.connect() as c:
            c.exec_driver_sql('PRAGMA foreign_keys=ON');c.commit()
    cfg=Config(str(config.BASE_DIR/'alembic.ini'));cfg.set_main_option('script_location',str(config.BASE_DIR/'migrations'))
    def upgrade(revision):
        with isolated.connect() as c:cfg.attributes['connection']=c;command.upgrade(cfg,revision)
    old_states=['draft','preparing','planning','ready','executing','commissioning','pilot','acceptance','completed','archived','suspended','unknown_2x']
    path=config.UPLOAD_DIR/('lifecycle-source-'+uuid4().hex);data=b'UNCHANGED business file\x00'*1000;path.write_bytes(data)
    try:
        upgrade(ScriptDirectory.from_config(cfg).get_revision('g3a28b000001').down_revision)
        with isolated.begin() as c:
            for status in old_states:
                c.execute(text("INSERT INTO projects(id,name,start_date,end_date,status,suspension,version,updated_at) VALUES(:id,:name,'2026-01-01','2026-12-31',:status,:suspension,7,'2026-01-01 12:00:00')"),
                    {'id':'old-'+status,'name':'原项目-'+status,'status':status,'suspension':json.dumps({'status_before':'pilot','reason':'原停工理由'}) if status=='suspended' else '{}'})
            c.execute(text("INSERT INTO change_logs(id,project_id,entity_type,entity_id,action,detail,created_at) VALUES('real-transition','old-commissioning','project','old-commissioning','update','项目状态: 现场实施 → 系统联调','2026-02-03 04:05:06')"))
            c.execute(text("INSERT INTO project_events(id,project_id,event_key,actual_at,note) VALUES('existing-real-event','old-pilot','go_live','2026-01-02 03:04:05','原人工事件不可覆盖')"))
            c.execute(text("INSERT INTO attachments(id,project_id,filename,stored_name,file_size) VALUES('original-file','old-commissioning','原始文件',:stored,:size)"),{'stored':path.name,'size':len(data)})
        upgrade('g3a28b000001');upgrade('g3a28b000001')
        with isolated.connect() as c:
            rows=c.execute(text('SELECT id,name,status,suspension,legacy_lifecycle,version,updated_at FROM projects')).mappings().all()
            by_id={r['id']:r for r in rows}
            for status in old_states:
                row=by_id['old-'+status]
                expected={'draft':'preparing','planning':'preparing','commissioning':'executing','pilot':'executing','unknown_2x':'suspended'}.get(status,status)
                assert row['status']==expected and row['name']=='原项目-'+status
                evidence=json.loads(row['legacy_lifecycle']) if isinstance(row['legacy_lifecycle'],str) else row['legacy_lifecycle']
                assert evidence['original_status']==status
                assert evidence['requires_repair'] is (status=='unknown_2x')
                assert str(row['updated_at']).startswith('2026-01-01 12:00:00')
            raw=by_id['old-suspended']['suspension'];suspension=json.loads(raw) if isinstance(raw,str) else raw
            assert suspension['status_before']=='executing' and suspension['reason']=='原停工理由'
            events=c.execute(text('SELECT project_id,event_key,actual_at,actual_date,actual_source,note FROM project_events')).mappings().all()
            restored=next(r for r in events if r['project_id']=='old-commissioning')
            assert str(restored['actual_at']).startswith('2026-02-03 04:05:06') and restored['actual_date'] is None
            source=json.loads(restored['actual_source']) if isinstance(restored['actual_source'],str) else restored['actual_source']
            assert source['change_log_id']=='real-transition' and source['kind']=='legacy_status_transition'
            assert not any(r['project_id']=='old-pilot' and r['event_key']=='commissioning_done' for r in events)
            preserved=next(r for r in events if r['project_id']=='old-pilot')
            assert str(preserved['actual_at']).startswith('2026-01-02 03:04:05') and preserved['note']=='原人工事件不可覆盖'
            assert c.execute(text('SELECT stored_name,file_size FROM attachments')).one()==(path.name,len(data))
            assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(data).digest()
            if not pg:assert c.exec_driver_sql('PRAGMA foreign_keys').scalar()==1
        upgrade('head')
        with isolated.connect() as c:
            assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
    finally:
        isolated.dispose();path.unlink(missing_ok=True)
        if pg:
            with engine.begin() as c:c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
