"""Named T30 edge preserves original quantity evidence without inventing identities."""
import io
import os
import json
import sqlalchemy as sa
import pytest
from sqlalchemy.orm import Session
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.config import BASE_DIR
from app.db import Base

REVISION='g3a30b000001'


def config():
    cfg=Config(str(BASE_DIR/'alembic.ini'))
    cfg.set_main_option('script_location',str(BASE_DIR/'migrations'))
    return cfg


def test_upgrade_unknown_identities_then_atomic_transfer_and_restart(monkeypatch,tmp_path):
    url=os.environ.get('AGVPM_T30_MIGRATION_URL') or 'sqlite:///'+str(tmp_path/'legacy.db')
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    cfg=config();graph=ScriptDirectory.from_config(cfg)
    parent=graph.get_revision(REVISION).down_revision
    command.upgrade(cfg,parent)
    engine=sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO users (id,username,password_hash,display_name,role,is_active,mfa_enabled,mfa_last_step,permission_version) VALUES ('actor','migrate','unused','迁移核对员','admin',true,false,-1,0)"))
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,manager,members) VALUES ('p','历史项目','2026-01-01','2026-12-31','executing','actor','[]')"))
        c.execute(sa.text("INSERT INTO vehicles (id,project_id,vehicle_type,model_name,quantity) VALUES ('v','p','潜伏式','原车型',3)"))
        c.execute(sa.text("INSERT INTO phases (id,project_id,name,sort_order) VALUES ('ph','p','实施',0)"))
        c.execute(sa.text("INSERT INTO modules (id,project_id,phase_id,name,sort_order) VALUES ('m','p','ph','原模块',0)"))
        c.execute(sa.text("INSERT INTO tasks (id,project_id,module_id,name,quantity_type,target_quantity,manually_completed,sort_order) VALUES ('t1','p','m','原单车测试','per_vehicle',2.4,false,0),('t2','p','m','原管理完成','per_vehicle',3.2,true,1)"))
        c.execute(sa.text("INSERT INTO daily_progress (id,project_id,task_id,user_id,work_date,completed_quantity,client_uuid) VALUES ('dp','p','t1','actor','2026-01-10',1.7,'old-real-uuid')"))
        # Real historical vehicle is preserved; neither quantity nor migration creates more.
        c.execute(sa.text("INSERT INTO vehicle_units (id,project_id,vehicle_id,asset_code,current_stage,current_status) VALUES ('unit','p','v','真实车001','production','fault')"))
        c.execute(sa.text("INSERT INTO vehicle_lifecycle_events (id,project_id,vehicle_unit_id,event_type,event_date,title,is_closed) VALUES ('fault','p','unit','fault','2026-01-09','原始传感器故障',false)"))
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,manager,members) VALUES ('unknown','原数量待补','2026-01-01','2026-12-31','executing','actor','[]')"))
        c.execute(sa.text("INSERT INTO phases (id,project_id,name,sort_order) VALUES ('uph','unknown','实施',0)"))
        c.execute(sa.text("INSERT INTO modules (id,project_id,phase_id,name,sort_order) VALUES ('um','unknown','uph','原模块',0)"))
        c.execute(sa.text("INSERT INTO tasks (id,project_id,module_id,name,quantity_type,target_quantity,manually_completed,sort_order) VALUES ('t3','unknown','um',:name,'per_vehicle',NULL,false,0)"),{'name':'原名称'*66+'原始'})
        c.execute(sa.text("INSERT INTO daily_progress (id,project_id,task_id,user_id,work_date,completed_quantity,client_uuid) VALUES ('dp-unknown','unknown','t3','actor','2026-01-10',2.2,'old-unknown-uuid')"))
        before=c.execute(sa.text('SELECT id,target_quantity,manually_completed FROM tasks ORDER BY id')).all()
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert c.execute(sa.text('SELECT id,target_quantity,manually_completed FROM tasks ORDER BY id')).all()==before
        assert float(c.execute(sa.text("SELECT SUM(completed_quantity) FROM daily_progress WHERE project_id='p'")).scalar())==1.7
        assert c.execute(sa.text('SELECT count(*) FROM vehicle_units')).scalar()==1
        assert c.execute(sa.text('SELECT title FROM vehicle_lifecycle_events')).scalar()=='原始传感器故障'
        assert c.execute(sa.text('SELECT current_stage,legacy_current_stage FROM vehicle_units')).one()==('planned','production')
        assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
    from app.models import User,VehicleProgressMigration,VehicleProgress
    from app.routers.vehicle_progress import change_matrix,MatrixChange
    from app.services.vehicle_progress import matrix,matrix_completion_blockers
    with Session(engine) as db:
        credits=db.query(VehicleProgressMigration).filter_by(project_id="p").order_by(VehicleProgressMigration.step_key).all()
        assert [r.total_count for r in credits]==[2,3]
        assert credits[0].source_metadata['completed_quantity']==1.7
        assert credits[0].source_metadata['completion_rounding_difference']==pytest.approx(.3)
        assert credits[1].source_metadata['manually_completed'] is True
        unknown=matrix(db,'unknown')
        assert unknown['summary']['completed']==2 and unknown['summary']['quantity_unknown']
        assert unknown['summary']['percent'] is None and unknown['units']==[]
        assert unknown['steps'][0]['expected_quantity'] is None
        assert len(unknown['steps'][0]['name'])>200
        assert matrix(db,'p')['summary']['completed']==5
        assert matrix_completion_blockers(db,'p')==[]  # unknown identities are a warning, not a new hard gate
        actor=db.get(User,'actor')
        from app.routers.vehicle_progress import clarify_historical_target,HistoricalTarget
        clarified=clarify_historical_target('unknown','legacy_t3',HistoricalTarget(expected_quantity=2,previous_quantity=None,reason='原项目单据核对两台'),actor,db)
        assert clarified['summary']['target']==2 and clarified['summary']['completed']==2
        assert clarified['summary']['percent']==100
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as stale:
            clarify_historical_target('unknown','legacy_t3',HistoricalTarget(expected_quantity=3,previous_quantity=None,reason='迟到旧页面'),actor,db)
        assert stale.value.status_code==409
        db.rollback()
        body=MatrixChange(cells=[{'vehicle_unit_id':'unit','step_key':'legacy_t1','version':0}],is_done=True,claim_migrated=True)
        result=change_matrix('p',body,actor,db)
        assert result['summary']['completed']==5 and result['summary']['unidentified_completed']==4
        fact=db.query(VehicleProgress).one()
        assert fact.done_on is None and fact.migrated and fact.done_by=='actor'
        body=MatrixChange(cells=[{'vehicle_unit_id':'unit','step_key':'legacy_t1','version':1}],is_done=False,reason='核对车号错误')
        result=change_matrix('p',body,actor,db)
        assert result['summary']['completed']==5 and result['summary']['unidentified_completed']==5
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert c.execute(sa.text('SELECT count(*) FROM vehicle_progress')).scalar()==1
        assert c.execute(sa.text('SELECT count(*) FROM vehicle_units')).scalar()==1
        assert c.execute(sa.text("SELECT SUM(unassigned_count) FROM vehicle_progress_migrations WHERE project_id='p'")).scalar()==5
        assert c.execute(sa.text('SELECT id,target_quantity,manually_completed FROM tasks ORDER BY id')).all()==before
        assert len(graph.get_heads())==1
        if engine.dialect.name=='sqlite': assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
    engine.dispose()


def test_t30_offline_requires_online_reconciliation():
    cfg=config();cfg.output_buffer=io.StringIO()
    parent=ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision
    with pytest.raises(RuntimeError,match='历史数量逐条保全'):
        command.upgrade(cfg,f'{parent}:{REVISION}',sql=True)
    assert 'CREATE TABLE vehicle_progress' in cfg.output_buffer.getvalue()
