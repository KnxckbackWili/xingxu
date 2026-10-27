"""Named T32 edge: retain all task-level facts and exact g30 source links."""
import io
import os
import json
import hashlib
import sqlalchemy as sa
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from tests.test_vehicle_progress_migration import config
from app.db import Base
REVISION='g3a32b000001'


def test_legacy_facts_no_automatic_pending_and_head_schema(monkeypatch,tmp_path):
    url=os.environ.get('AGVPM_T32_MIGRATION_URL') or 'sqlite:///'+str(tmp_path/'old.db')
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    cfg=config();graph=ScriptDirectory.from_config(cfg)
    command.upgrade(cfg,graph.get_revision(REVISION).down_revision)
    engine=sa.create_engine(url)
    with engine.begin() as c:
        statements=[
            "INSERT INTO users (id,username,password_hash,display_name,role,is_active,mfa_enabled,mfa_last_step,permission_version) VALUES ('actor','migrate','unused','原操作者','admin',true,false,-1,0)",
            "INSERT INTO projects (id,name,start_date,end_date,status,manager,members) VALUES ('p','历史检查','2026-01-01','2026-12-31','executing','actor','[]')",
            "INSERT INTO vehicles (id,project_id,vehicle_type,model_name,quantity) VALUES ('v','p','潜伏式','型号',2)",
            "INSERT INTO vehicle_units (id,project_id,vehicle_id,asset_code) VALUES ('u','p','v','原真实车号')",
            "INSERT INTO phases (id,project_id,name,sort_order) VALUES ('ph','p','实施',0)",
            "INSERT INTO modules (id,project_id,phase_id,name) VALUES ('m','p','ph','原模块')",
            "INSERT INTO tasks (id,project_id,module_id,name,quantity_type,target_quantity,unit,safety_flag,applicable_vehicle_types) VALUES ('t','p','m','旧按车工作','per_vehicle',2,'台',false,'[]')",
            "INSERT INTO project_vehicle_steps (id,project_id,key,name,sort_order,source_task_id,expected_quantity) VALUES ('s','p','legacy_t','历史环节：旧按车工作',0,'t',2)",
            "INSERT INTO vehicle_progress_migrations (id,project_id,step_key,total_count,unassigned_count,source_metadata) VALUES ('credit','p','legacy_t',2,2,'{}')",
            "INSERT INTO check_items (id,task_id,project_id,name,is_safety_critical,is_required,is_applicable,is_done,failed,done_by,done_at,version) VALUES ('pass','t','p','历史安全通过',true,true,true,true,false,'actor','2026-01-02 03:04:05',7),('pending','t',NULL,'历史必检未查',false,true,true,false,false,NULL,NULL,2)"]
        for statement in statements:c.execute(sa.text(statement))
        fields='id,task_id,project_id,name,is_safety_critical,is_required,is_applicable,is_done,failed,done_by,done_at,version'
        before=c.execute(sa.text('SELECT '+fields+' FROM check_items ORDER BY id')).all()
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert c.execute(sa.text('SELECT '+fields+' FROM check_items ORDER BY id')).all()==before
        assert c.execute(sa.text('SELECT vehicle_step_key FROM tasks')).scalar()=='legacy_t'
        assert c.execute(sa.text('SELECT count(*) FROM check_items WHERE vehicle_unit_id IS NOT NULL')).scalar()==0
        assert c.execute(sa.text('SELECT source_check_id,source_version FROM vehicle_check_definitions ORDER BY source_check_id')).all()==[('pass',7),('pending',2)]
        assert c.execute(sa.text('SELECT total_count,unassigned_count FROM vehicle_progress_migrations')).one()==(2,2)
        assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
        if engine.dialect.name=='sqlite':assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
    from sqlalchemy.orm import Session
    from app.services.acceptance import acceptance_scope_fingerprint
    payload={'version':1,'tasks':[{'id':'t','name':'旧按车工作','description':'','quantity_type':'per_vehicle','target_quantity':2,'unit':'台','safety_flag':False,'applicable_vehicle_types':[],'deliverables':[]}],
        'required_deliveries':[],'checks':[{'id':'pass','task_id':'t','name':'历史安全通过','description':'','required':True,'safety':True,'applicable':True},{'id':'pending','task_id':'t','name':'历史必检未查','description':'','required':True,'safety':False,'applicable':True}],
        'vehicles':[{'id':'v','type':'潜伏式','model':'型号','quantity':2,'configuration':{}}]}
    with Session(engine) as db:assert acceptance_scope_fingerprint(db,'p')==hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    command.upgrade(cfg,'head')
    with engine.connect() as c:assert c.execute(sa.text('SELECT count(*) FROM vehicle_check_definitions')).scalar()==2
    assert len(graph.get_heads())==1
    engine.dispose()


def test_t32_offline_refuses_before_partial_ddl():
    cfg=config();cfg.output_buffer=io.StringIO()
    parent=ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision
    with pytest.raises(RuntimeError,match='T32须在线'):command.upgrade(cfg,f'{parent}:{REVISION}',sql=True)
    assert 'CREATE TABLE vehicle_check_definitions' not in cfg.output_buffer.getvalue()
