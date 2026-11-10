"""Weekly intent never grants execution, private drafts or stale authority."""
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import pytest
from fastapi import HTTPException
from app.db import SessionLocal, engine
from app.models import Project, User, Task, WeeklyPlanCell, VehicleUnit, Vehicle, CheckItem, VehicleProgress, ProjectVehicleStep, VehicleLifecycleEvent, Notification
from tests.test_weekly_plans import setup, create_cell


def test_explicit_cars_obey_work_applicability(client,pm_headers):
    pid,units,ph,task=setup(client,pm_headers,vehicle=True)
    create_cell(client,pm_headers,pid,task,mode='finish',target_count=2)
    create_cell(client,pm_headers,pid,task,week_start='2001-01-08',scope={'vehicle_unit_ids':[units[0]]},mode='finish',target_count=1)
    with SessionLocal() as db:
        db.get(Task,task['id']).applicable_vehicle_types=['仅指定的其它车型'];db.commit()
    response=client.post(f'/api/projects/{pid}/weekly-plans',headers=pm_headers,json={'task_id':task['id'],'week_start':'2001-01-15','scope':{'vehicle_unit_ids':[units[0]]}})
    assert response.status_code==400


def test_plan_completion_rechecks_exact_required_and_safety_checks(client,pm_headers):
    pid,units,ph,task=setup(client,pm_headers,vehicle=True)
    row=create_cell(client,pm_headers,pid,task,mode='finish',target_count=2)
    with SessionLocal() as db:
        for uid in units:db.add(VehicleProgress(project_id=pid,vehicle_unit_id=uid,step_key='arrival_inspection',is_done=True,done_on=date(2001,1,3)))
        db.get(Task,task['id']).manually_completed=True;db.get(Task,task['id']).manual_completed_reason='不能覆盖安全';db.commit()
    path=f'/api/projects/{pid}/weekly-plans?week_start=2001-01-01&weeks=1'
    with SessionLocal() as db:
        from uuid import uuid4
        from app.services.vehicle_checks import snapshot_definitions, generate_for_units
        definition=CheckItem(id=str(uuid4()),name='该车必检',is_required=True,is_safety_critical=True,is_done=False,version=0)
        current=db.get(Task,task['id']);snapshot_definitions(db,current,[definition])
        generate_for_units(db,pid,[db.get(VehicleUnit,units[0])],current)
        db.commit();exact_id=db.query(CheckItem).filter_by(task_id=task['id'],vehicle_unit_id=units[0]).one().id
    facts=client.get(path,headers=pm_headers).json()['cells'][0]['completion'];assert facts['completed_count']==1 and not facts['is_complete']
    with SessionLocal() as db:db.get(CheckItem,exact_id).is_done=True;db.commit()
    facts=client.get(path,headers=pm_headers).json()['cells'][0]['completion'];assert facts['completed_count']==2 and facts['is_complete']


def test_extreme_date_is_a_clear_validation_error(client,pm_headers):
    pid,units,ph,task=setup(client,pm_headers)
    assert client.get(f'/api/projects/{pid}/weekly-plans?week_start=9999-12-31',headers=pm_headers).status_code==400
    assert client.post(f'/api/projects/{pid}/weekly-plans',headers=pm_headers,json={'task_id':task['id'],'week_start':'9999-12-31'}).status_code==400


def test_pg_stale_actor_revocation_is_rechecked_after_project_lock(client,pm_headers):
    if engine.dialect.name!='postgresql':pytest.skip('真实PG双会话权限锁探针')
    from app.services import weekly_plans
    from app.services.record_lock import lock_writable_project
    pid,units,ph,task=setup(client,pm_headers);entered=Event()
    def attempt():
        with SessionLocal() as db:
            actor=db.query(User).filter_by(username='pm').one();p=db.get(Project,pid);entered.set()
            try:weekly_plans.create(db,p,actor,{'task_id':task['id'],'week_start':date(2001,1,1)})
            except HTTPException as exc:db.rollback();return exc.status_code
            db.commit();return 200
    with SessionLocal() as first,ThreadPoolExecutor(max_workers=1) as pool:
        actor=first.query(User).filter_by(username='pm').one();lock_writable_project(first,first.get(Project,pid),actor)
        actor.is_active=False;first.flush()
        future=pool.submit(attempt);assert entered.wait(2);assert not future.done();first.commit();assert future.result(timeout=10) in (401,403)
    with SessionLocal() as db:assert db.query(WeeklyPlanCell).filter_by(project_id=pid).count()==0


def test_excel_phase_filter_does_not_include_other_phase_warning_text(client,pm_headers):
    from io import BytesIO
    from openpyxl import load_workbook
    from tests.test_work_items_t34 import phase,create
    pid,units,ph,task=setup(client,pm_headers)
    create_cell(client,pm_headers,pid,task)
    other=client.post(f'/api/projects/{pid}/work-phases',headers=pm_headers,json={'name':'不在导出阶段'}).json()['id']
    work=create(client,pm_headers,pid,other,name='UNSELECTED-WORK-PRIVATE-TEXT',kind='vehicle',vehicle_step_key='arrival_inspection')
    create_cell(client,pm_headers,pid,work,mode='finish',target_count=9)
    response=client.get(f'/api/projects/{pid}/weekly-plans/export/excel?week_start=2001-01-01&weeks=1&phase_id={ph}',headers=pm_headers)
    assert response.status_code==200,response.text
    book=load_workbook(BytesIO(response.content))
    text=' '.join(str(value) for sheet in book for row in sheet.values for value in row)
    assert 'UNSELECTED-WORK-PRIVATE-TEXT' not in text and task['name'] in text



def test_retention_keeps_full_weekly_row(client,pm_headers):
    from app.services.project_retention import project_retention_snapshot
    pid,units,ph,task=setup(client,pm_headers)
    create_cell(client,pm_headers,pid,task,notes='原周计划完整说明')
    with SessionLocal() as db:
        retained=project_retention_snapshot(db,db.get(Project,pid))['records']['weekly_plan_cells'][0]
        assert retained['notes']=='原周计划完整说明' and retained['version']==0
        assert set(retained)=={column.name for column in WeeklyPlanCell.__table__.columns}
