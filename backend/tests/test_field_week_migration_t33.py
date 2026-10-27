"""T40→T33 retains published plans and never infers an actual operator."""
import os
from datetime import date,datetime
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from tests.test_vehicle_progress_migration import config
from app.db import Base


def test_named_field_edge_preserves_plans_and_requires_evidence_for_actuals(monkeypatch,tmp_path):
    url=os.environ.get('AGVPM_T33_MIGRATION_URL') or 'sqlite:///'+str(tmp_path/'field.db')
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    cfg=config();graph=ScriptDirectory.from_config(cfg)
    assert len(graph.get_heads())==1
    command.upgrade(cfg,graph.get_revision('g3a33b000001').down_revision)
    engine=sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO users (id,username,password_hash,display_name,role,is_active,mfa_enabled,mfa_last_step,permission_version) VALUES ('original-user','original','unused','原计划负责人','worker',true,false,-1,0)"))
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,manager,members) VALUES ('original-project','原计划项目','2026-01-01','2026-12-31','executing','original-user','[\"original-user\"]')"))
        c.execute(sa.text("INSERT INTO phases (id,project_id,name,sort_order) VALUES ('original-phase','original-project','实施工作',3)"))
        c.execute(sa.text("INSERT INTO tasks (id,project_id,phase_id,name,quantity_type,manually_completed,version) VALUES ('original-work','original-project','original-phase','原已完成工作','fixed',true,7)"))
        metadata=sa.MetaData();table=sa.Table('weekly_plan_cells',metadata,autoload_with=c)
        c.execute(table.insert().values(id='original-cell',project_id='original-project',task_id='original-work',scope_key='all',scope={},
            week_start=date(2026,10,26),mode='finish',assignee_ids=['original-user'],published=True,published_by='original-user',
            published_at=datetime(2026,10,25,3),is_cancelled=False,notes='原计划备注与原文来源',source_metadata={'original':'保留'},
            created_at=datetime(2026,10,25,2),updated_at=datetime(2026,10,25,3),created_by='original-user',updated_by='original-user',version=4))
        original_tables={name:sa.Table(name,sa.MetaData(),autoload_with=c) for name in ('weekly_plan_cells','users','tasks','projects')}
        before={name:c.execute(sa.select(table)).all() for name,table in original_tables.items()}
    command.upgrade(cfg,'head')
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert c.execute(sa.text('SELECT count(*) FROM field_operations')).scalar_one()==0
        assert {name:c.execute(sa.select(table)).all() for name,table in original_tables.items()}==before
        assert c.execute(sa.text("SELECT intent_review_required FROM weekly_plan_cells WHERE id='original-cell'")).scalar() in (False,0)
        assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
        if engine.dialect.name=='sqlite':assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
    engine.dispose()
