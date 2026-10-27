"""Named T40 edge preserves exact daily sources without inventing execution."""
import io
import json
import os
import math
from datetime import date, datetime
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from tests.test_vehicle_progress_migration import config
from app.db import Base

REVISION = 'g3a40b000001'


def _plain(value):
    if isinstance(value,float) and not math.isfinite(value):
        return {'invalid_original_number':str(value)}
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def test_daily_rows_roll_up_with_exact_sources_and_publication_not_actuals(monkeypatch, tmp_path):
    url = os.environ.get('AGVPM_T40_MIGRATION_URL') or 'sqlite:///' + str(tmp_path / 'old-daily.db')
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    cfg = config(); graph = ScriptDirectory.from_config(cfg)
    command.upgrade(cfg, graph.get_revision(REVISION).down_revision)
    engine = sa.create_engine(url)
    with engine.begin() as c:
        statements = [
            "INSERT INTO users (id,username,password_hash,display_name,role,is_active,mfa_enabled,mfa_last_step,permission_version) VALUES ('a','a','unused','原甲','pm',true,false,-1,0),('b','b','unused','原乙','worker',true,false,-1,0)",
            "INSERT INTO projects (id,name,start_date,end_date,status,manager,members) VALUES ('p','历史按日计划','2001-01-01','2001-02-01','executing','a','[\"b\"]')",
            "INSERT INTO phases (id,project_id,name,sort_order) VALUES ('ph','p','原阶段',1)",
            "INSERT INTO tasks (id,project_id,phase_id,name,quantity_type,target_quantity,unit,manually_completed,version,vehicle_step_key) VALUES ('car','p','ph','原车辆工作','per_vehicle',2.7,'台',false,9,'arrival_inspection'),('other','p','ph','原其他工作','manual',3,'套',false,5,NULL)",
            "INSERT INTO daily_progress (id,project_id,task_id,user_id,work_date,completed_quantity,client_uuid,note) VALUES ('report','p','car','a','2001-01-03',0.7,'original-report-uuid','原发生说明')",
            "INSERT INTO schedule_entries (id,project_id,task_id,work_date,assignee_id,planned_quantity,status,is_confirmed,is_locked,version,notes) VALUES ('a1','p','car','2001-01-01','a',0.25,'planned',true,true,7,'原甲说明'),('a2','p','car','2001-01-03','b',0.75,'done',true,false,8,'原乙说明'),('draft','p','car','2001-01-04','a',0,'planned',false,false,2,'未发布0量'),('fraction','p','car','2001-01-08','b',0.5,'planned',true,false,3,'小数待核对'),('cancelled','p','car','2001-01-02','a',5,'skipped',true,false,4,'已跳过原行'),('other-plan','p','other','2001-01-01',NULL,3,'planned',false,false,6,'非车辆数量来源')",
        ]
        for statement in statements: c.execute(sa.text(statement))
        extras = [
            ('null','car','2001-01-15',None),
            ('mixed-known','car','2001-01-22',1),('mixed-null','car','2001-01-23',None),
            ('invalid','car','2001-01-29',float('inf')),('invalid-known','car','2001-01-30',2),
            ('other-null','other','2001-01-08',None),('other-known','other','2001-01-09',3),
        ]
        for identity,tid,day,quantity in extras:
            c.execute(sa.text("INSERT INTO schedule_entries (id,project_id,task_id,work_date,planned_quantity,status,is_confirmed,notes,version) VALUES (:id,'p',:tid,:day,:qty,'planned',true,'原未知量保留',4)"),{'id':identity,'tid':tid,'day':day,'qty':quantity})
        before = {r['id']: dict(r) for r in c.execute(sa.text('SELECT * FROM schedule_entries ORDER BY id')).mappings()}
        original_tasks = c.execute(sa.text('SELECT id,target_quantity,unit,manually_completed,version FROM tasks ORDER BY id')).all()
        original_reports = c.execute(sa.text('SELECT * FROM daily_progress ORDER BY id')).all()
    command.upgrade(cfg, 'head')
    with engine.connect() as c:
        assert {r['id']: dict(r) for r in c.execute(sa.text('SELECT * FROM schedule_entries ORDER BY id')).mappings()} == before
        assert c.execute(sa.text('SELECT id,target_quantity,unit,manually_completed,version FROM tasks ORDER BY id')).all() == original_tasks
        assert c.execute(sa.text('SELECT * FROM daily_progress ORDER BY id')).all() == original_reports
        rows = list(c.execute(sa.text('SELECT * FROM weekly_plan_cells')).mappings()); assert len(rows) == 9
        preserved = {}
        for row in rows:
            source = json.loads(row['source_metadata']) if isinstance(row['source_metadata'], str) else row['source_metadata']
            for old in source['original_entries']: preserved[old['id']] = old
            assert row['published_at'] is None and row['published_by'] is None
            assert row['created_by'] is None and row['updated_by'] is None and row['version'] == 0
            ids = source['original_entry_ids']
            if ids == ['a1', 'a2']:
                assert source['original_planned_sum'] == '1.00' and row['target_count'] == 1 and row['published']
                owners = json.loads(row['assignee_ids']) if isinstance(row['assignee_ids'], str) else row['assignee_ids']
                assert owners == ['a', 'b'] and not row['is_cancelled']
            elif ids == ['fraction']:
                assert row['mode'] == 'finish' and row['target_count'] is None and source['migration_review_required'] and row['intent_review_required']
            elif ids == ['draft']:
                assert row['mode'] == 'in_progress' and row['target_count'] is None and not row['published']
            elif ids == ['cancelled']:
                assert row['is_cancelled'] and row['published'] and row['target_count'] == 5
            elif ids == ['other-plan']:
                assert row['mode'] == 'finish' and row['target_count'] is None
            elif ids in (['null'],['mixed-known','mixed-null'],['invalid','invalid-known'],['other-null','other-known']):
                assert row['mode']=='finish' and row['target_count'] is None and row['intent_review_required']
                assert source['original_planned_sum'] is None and source['migration_review_required']
                assert source['unknown_quantity_count']==1
                assert source['known_planned_sum']=={'null':'0','mixed-known':'1.0','invalid':'2.0','other-null':'3.0'}[ids[0]]
                assert source['null_quantity_count']==(0 if ids[0]=='invalid' else 1)
                assert source['invalid_quantity_count']==(1 if ids[0]=='invalid' else 0)
        assert preserved == {key: {k: _plain(v) for k,v in row.items()} for key,row in before.items()}
        assert c.execute(sa.text("SELECT count(*) FROM change_logs WHERE action='migrate_weeks'")).scalar() == 1
        assert compare_metadata(MigrationContext.configure(c, opts={'compare_server_default': True}), Base.metadata) == []
        if engine.dialect.name == 'sqlite': assert c.execute(sa.text('PRAGMA foreign_key_check')).all() == []
    command.upgrade(cfg, 'head')
    with engine.connect() as c: assert c.execute(sa.text('SELECT count(*) FROM weekly_plan_cells')).scalar() == 9
    assert len(graph.get_heads()) == 1
    engine.dispose()


def test_named_t40_offline_refuses_before_partial_ddl():
    cfg = config(); cfg.output_buffer = io.StringIO()
    parent = ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision
    with pytest.raises(RuntimeError, match='T40须在线'): command.upgrade(cfg, f'{parent}:{REVISION}', sql=True)
    assert 'CREATE TABLE weekly_plan_cells' not in cfg.output_buffer.getvalue()


def test_t40_wrong_project_source_rolls_back_schema_and_original_rows(monkeypatch,tmp_path):
    url=os.environ.get('AGVPM_T40_ROLLBACK_URL') or 'sqlite:///'+str(tmp_path/'wrong-owner.db')
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    cfg=config();parent=ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision
    command.upgrade(cfg,parent);engine=sa.create_engine(url)
    with engine.begin() as c:
        for statement in [
            "INSERT INTO projects (id,name,start_date,end_date,status) VALUES ('owner','工作归属','2001-01-01','2001-02-01','executing'),('other','日程错误归属','2001-01-01','2001-02-01','executing')",
            "INSERT INTO phases (id,project_id,name) VALUES ('ph','owner','实施')",
            "INSERT INTO tasks (id,project_id,phase_id,name,quantity_type,version) VALUES ('t','owner','ph','原工作','fixed',3)",
            "INSERT INTO schedule_entries (id,project_id,task_id,work_date,planned_quantity,is_confirmed,status) VALUES ('bad','other','t','2001-01-01',1,true,'planned')",
        ]:c.execute(sa.text(statement))
        original=c.execute(sa.text('SELECT * FROM schedule_entries')).all()
    with pytest.raises(RuntimeError,match='原日程工作归属不一致'):command.upgrade(cfg,REVISION)
    with engine.connect() as c:
        assert 'weekly_plan_cells' not in sa.inspect(c).get_table_names()
        assert c.execute(sa.text('SELECT version_num FROM alembic_version')).scalar()==parent
        assert c.execute(sa.text('SELECT * FROM schedule_entries')).all()==original
        if engine.dialect.name=='sqlite':assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
    engine.dispose()
