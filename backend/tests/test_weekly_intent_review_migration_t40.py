"""A previously-applied QA g40 upgrades through g33 without hand-written DDL."""
from datetime import datetime
import json,os
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db import Base
from tests.test_vehicle_progress_migration import config
from migrations.v3_weekly_intent import summarize

REVISION='g3a40b000002'


def test_previously_applied_g40_unknown_definitions_upgrade_without_recreating_sources(monkeypatch,tmp_path):
    url=os.environ.get('AGVPM_T40_REVIEW_MIGRATION_URL') or 'sqlite:///'+str(tmp_path/'qa-g40.db')
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    cfg=config();parent=ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision;command.upgrade(cfg,parent)
    engine=sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status) VALUES ('p','QA原计划','2001-01-01','2001-03-01','executing')"))
        c.execute(sa.text("INSERT INTO phases (id,project_id,name) VALUES ('ph','p','实施')"))
        c.execute(sa.text("INSERT INTO tasks (id,project_id,phase_id,name,quantity_type,manually_completed) VALUES ('car','p','ph','车辆工作','per_vehicle',false),('other','p','ph','非车辆工作','fixed',true)"))
        table=sa.Table('weekly_plan_cells',sa.MetaData(),autoload_with=c)
        for tid in ('car','other'):
            originals=[{'id':tid+'-known','planned_quantity':1.0},{'id':tid+'-null','planned_quantity':None}]
            source={'kind':'t40_legacy_daily_rollup','original_entries':originals,'original_entry_ids':[r['id'] for r in originals],
                'original_planned_sum':'1.0','migration_review_required':False,'publication_actor':'unknown','publication_time':'unknown'}
            c.execute(table.insert().values(id=tid,project_id='p',task_id=tid,scope_key='all:legacy:published:active',scope={'vehicle_unit_ids':[]},
                week_start=datetime(2001,1,1).date(),mode='finish' if tid=='car' else 'in_progress',target_count=1 if tid=='car' else None,
                assignee_ids=[],published=True,is_cancelled=False,notes='原备注不可丢',source_metadata=source,
                created_at=datetime(2001,1,1,10),updated_at=datetime(2001,1,1,11),version=5))
        before={r['id']:dict(r) for r in c.execute(sa.select(table)).mappings()}
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        table=sa.Table('weekly_plan_cells',sa.MetaData(),autoload_with=c)
        after={r['id']:dict(r) for r in c.execute(sa.select(table)).mappings()}
        for identity,row in after.items():
            old=before[identity];assert row['intent_review_required'] and row['mode']=='finish' and row['target_count'] is None and row['version']==6
            for key in ('id','project_id','task_id','scope_key','scope','week_start','assignee_ids','published','is_cancelled','notes','created_at','updated_at'):
                assert row[key]==old[key]
            assert row['source_metadata']['original_entries']==old['source_metadata']['original_entries']
            assert row['source_metadata']['known_planned_sum']=='1.0' and row['source_metadata']['original_planned_sum'] is None
            assert row['source_metadata']['unknown_quantity_count']==1 and row['source_metadata']['migration_review_required']
        assert c.execute(sa.text("SELECT count(*) FROM change_logs WHERE action='review_plan_intent'")).scalar()==1
        assert c.execute(sa.text('SELECT count(*) FROM daily_progress')).scalar()==0
        assert compare_metadata(MigrationContext.configure(c,opts={'compare_server_default':True}),Base.metadata)==[]
        if engine.dialect.name=='sqlite':assert c.execute(sa.text('PRAGMA foreign_key_check')).all()==[]
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert {r['id']:dict(r) for r in c.execute(sa.select(table)).mappings()}==after
    engine.dispose()


def test_frozen_arithmetic_distinguishes_unknown_and_retains_exact_large_finite_sum():
    for value in (None,float('inf'),float('-inf'),float('nan')):
        result=summarize([{'planned_quantity':1},{'planned_quantity':value}],True)
        assert result['target_count'] is None and result['original_planned_sum'] is None
        assert result['known_planned_sum']=='1' and result['unknown_quantity_count']==1 and result['migration_review_required']
        assert result['mode']=='finish'
    exact=summarize([{'planned_quantity':1e30},{'planned_quantity':.25}],True)
    assert exact['known_planned_sum']=='1000000000000000000000000000000.25' and exact['target_count'] is None


def test_review_revision_offline_refuses_before_adding_column():
    import io,pytest
    cfg=config();cfg.output_buffer=io.StringIO()
    parent=ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision
    with pytest.raises(RuntimeError,match='T40计划未知量须在线'):command.upgrade(cfg,f'{parent}:{REVISION}',sql=True)
    assert 'ADD COLUMN intent_review_required' not in cfg.output_buffer.getvalue()


def test_review_missing_frozen_source_rolls_back_added_column_and_rows(monkeypatch,tmp_path):
    import pytest
    url=os.environ.get('AGVPM_T40_REVIEW_ROLLBACK_URL') or 'sqlite:///'+str(tmp_path/'bad-qa-source.db')
    monkeypatch.setattr('app.config.DATABASE_URL',url)
    cfg=config();parent=ScriptDirectory.from_config(cfg).get_revision(REVISION).down_revision;command.upgrade(cfg,parent)
    engine=sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status) VALUES ('p','QA待核对','2001-01-01','2001-03-01','executing')"))
        c.execute(sa.text("INSERT INTO phases (id,project_id,name) VALUES ('ph','p','实施')"))
        c.execute(sa.text("INSERT INTO tasks (id,project_id,phase_id,name,quantity_type) VALUES ('t','p','ph','原工作','fixed')"))
        table=sa.Table('weekly_plan_cells',sa.MetaData(),autoload_with=c)
        c.execute(table.insert().values(id='bad',project_id='p',task_id='t',scope_key='all',scope={},week_start=datetime(2001,1,1).date(),
            mode='finish',target_count=None,assignee_ids=[],published=True,is_cancelled=False,notes='保留异常原件供核对',
            source_metadata={'kind':'t40_legacy_daily_rollup','original_entries':[]},created_at=datetime(2001,1,1),updated_at=datetime(2001,1,1),version=3))
        before=list(c.execute(sa.select(table)).mappings())
    with pytest.raises(RuntimeError,match='原周计划量来源缺失'):command.upgrade(cfg,REVISION)
    with engine.connect() as c:
        assert 'intent_review_required' not in {col['name'] for col in sa.inspect(c).get_columns('weekly_plan_cells')}
        assert c.execute(sa.text('SELECT version_num FROM alembic_version')).scalar()==parent
        assert list(c.execute(sa.select(table)).mappings())==before
    engine.dispose()
