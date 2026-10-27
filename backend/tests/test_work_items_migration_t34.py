"""Named T34 edge, original quantities/check rows/source IDs and no fabricated time."""
import io
import os
import json
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from tests.test_vehicle_progress_migration import config
from app.db import Base
REVISION='g3a34b000001'


def test_legacy_work_hierarchy_quantity_and_checked_completion_survive(monkeypatch,tmp_path):
    url=os.environ.get('AGVPM_T34_MIGRATION_URL') or 'sqlite:///'+str(tmp_path/'old-work.db')
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    cfg=config();graph=ScriptDirectory.from_config(cfg);command.upgrade(cfg,graph.get_revision(REVISION).down_revision)
    engine=sa.create_engine(url)
    with engine.begin() as c:
        statements=[
            "INSERT INTO users (id,username,password_hash,display_name,role,is_active,mfa_enabled,mfa_last_step,permission_version) VALUES ('actor','migrate','unused','原操作者','pm',true,false,-1,0)",
            "INSERT INTO projects (id,name,start_date,end_date,status,manager,members) VALUES ('p','历史工作','2026-01-01','2026-12-31','executing','actor','[]')",
            "INSERT INTO phases (id,name,sort_order) VALUES ('original-shared-phase','原阶段',3)",
            "INSERT INTO modules (id,project_id,phase_id,name,preparation_conditions) VALUES ('m','p','original-shared-phase','原模块标签','[\"need_wms\"]')",
            "INSERT INTO tasks (id,project_id,module_id,name,description,quantity_type,target_quantity,unit,manually_completed,manual_completed_reason,version) VALUES ('complete','p','m','原非车辆工作','施工说明完整','manual',2.4,'套',false,'',7),('pending','p','m','原未完成工作','原说明','fixed',3,'项',false,'',2),('safety','p','m','未核验安全','原安全说明','fixed',1,'项',false,'',4),('manual','p','m','原手动完成','原理由保留','manual',99,'件',true,'原管理确认',8),('car','p','m','原车辆工作','不猜环节','per_vehicle',2.7,'台',false,'',9)",
            "INSERT INTO daily_progress (id,project_id,task_id,user_id,work_date,completed_quantity,client_uuid,note) VALUES ('report','p','complete','actor','2026-01-03',2.4,'original-complete-uuid','原填报说明'),('partial','p','pending','actor','2026-01-04',2,'original-pending-uuid','原部分完成'),('safe-report','p','safety','actor','2026-01-05',1,'original-safety-uuid','数量不替代安全')",
            "INSERT INTO check_items (id,task_id,project_id,name,is_required,is_safety_critical,is_applicable,is_done,failed,version) VALUES ('ci-pass','complete','p','原通过',true,false,true,true,false,5),('ci-safe','safety',NULL,'原安全未检',true,true,true,false,false,6)"]
        for statement in statements:c.execute(sa.text(statement))
        raw=c.execute(sa.text('SELECT id,task_id,user_id,work_date,completed_quantity,client_uuid,note FROM daily_progress ORDER BY id')).all()
        checks=c.execute(sa.text('SELECT id,task_id,project_id,is_done,failed,version,vehicle_unit_id FROM check_items ORDER BY id')).all()
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert c.execute(sa.text('SELECT count(*) FROM field_operations')).scalar()==0
        assert c.execute(sa.text('SELECT id,task_id,user_id,work_date,completed_quantity,client_uuid,note FROM daily_progress ORDER BY id')).all()==raw
        assert c.execute(sa.text('SELECT id,task_id,project_id,is_done,failed,version,vehicle_unit_id FROM check_items ORDER BY id')).all()==checks
        assert c.execute(sa.text('SELECT count(*) FROM modules')).scalar()==1
        rows={row['id']:row for row in c.execute(sa.text('SELECT * FROM tasks')).mappings()}
        assert rows['complete']['manually_completed'] and rows['complete']['manual_completed_by'] is None and rows['complete']['manual_completed_at'] is None
        assert not rows['pending']['manually_completed'] and not rows['safety']['manually_completed']
        assert rows['manual']['manually_completed'] and rows['manual']['manual_completed_reason']=='原管理确认'
        assert rows['car']['vehicle_step_key'] is None and rows['car']['target_quantity']==2.7
        assert rows['complete']['target_quantity']==2.4 and rows['complete']['unit']=='套' and rows['complete']['version']==7
        for row in rows.values():
            assert row['module_id']=='m' and row['group_label']=='原模块标签'
            assert c.execute(sa.text('SELECT project_id FROM phases WHERE id=:id'),{'id':row['phase_id']}).scalar()=='p'
            source=json.loads(row['legacy_work_snapshot']) if isinstance(row['legacy_work_snapshot'],str) else row['legacy_work_snapshot']
            assert source['task']['id']==row['id'] and source['phase']['id']=='original-shared-phase'
        source=json.loads(rows['complete']['legacy_work_snapshot']) if isinstance(rows['complete']['legacy_work_snapshot'],str) else rows['complete']['legacy_work_snapshot']
        assert not source['task']['manually_completed'] and source['completed_quantity']==2.4 and source['report_count']==1
        assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
        if engine.dialect.name=='sqlite':assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
    command.upgrade(cfg,'head')
    with engine.connect() as c:assert c.execute(sa.text("SELECT count(*) FROM change_logs WHERE action='migrate_work'")).scalar()==1
    assert len(graph.get_heads())==1
    engine.dispose()


def test_named_t34_offline_refuses_before_partial_ddl():
    cfg=config();cfg.output_buffer=io.StringIO()
    parent=ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision
    with pytest.raises(RuntimeError,match='T34须在线'):command.upgrade(cfg,f'{parent}:{REVISION}',sql=True)
    assert 'ALTER TABLE tasks' not in cfg.output_buffer.getvalue()
