"""Weekly intent never grants execution, private drafts or stale authority."""
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import pytest
from fastapi import HTTPException
from app.db import SessionLocal, engine
from app.models import (Project, User, Task, WeeklyPlanCell, VehicleUnit, Vehicle,
    CheckItem, VehicleProgress, VehicleProgressMigration, ProjectVehicleStep,
    UserUnavailability, VehicleLifecycleEvent, Notification)
from tests.test_weekly_plans import setup, create_cell, publish


def test_member_warnings_exclude_unpublished_targets_and_private_absence_details(client, pm_headers, worker_headers):
    pid, units, ph, task = setup(client, pm_headers, vehicle=True)
    with SessionLocal() as db:
        worker = db.query(User).filter_by(username='worker1').one(); wid = worker.id
        project = db.get(Project,pid); project.members = [wid]; manager = project.manager
        db.add(UserUnavailability(user_id=manager,start_date=date(2001,1,1),end_date=date(2001,1,7),reason='私密原因',note='私密备注'))
        db.commit()
    visible = create_cell(client,pm_headers,pid,task,mode='finish',target_count=1,assignee_ids=[manager])
    assert publish(client,pm_headers,pid,visible).status_code == 200
    create_cell(client,pm_headers,pid,task,week_start='2001-01-08',mode='finish',target_count=99)
    response = client.get(f'/api/projects/{pid}/weekly-plans?week_start=2001-01-01&weeks=2',headers=worker_headers)
    assert response.status_code == 200,response.text
    data=response.json(); assert len(data['cells']) == 1 and data['summary']['draft_count'] is None
    assert next(w for w in data['warnings'] if w['code']=='target_mismatch')['planned_count'] == 1
    unavailable=next(w['unavailability'] for w in data['warnings'] if w['code']=='unavailable')
    assert 'reason' not in unavailable and 'note' not in unavailable
    assert '私密原因' not in response.text and '私密备注' not in response.text


def test_overlapping_scope_warns_and_explicit_cars_obey_work_applicability(client,pm_headers):
    pid,units,ph,task=setup(client,pm_headers,vehicle=True)
    create_cell(client,pm_headers,pid,task,mode='finish',target_count=2)
    create_cell(client,pm_headers,pid,task,week_start='2001-01-08',scope={'vehicle_unit_ids':[units[0]]},mode='finish',target_count=1)
    data=client.get(f'/api/projects/{pid}/weekly-plans?week_start=2001-01-01&weeks=2',headers=pm_headers).json()
    assert any(w['code']=='scope_overlap' for w in data['warnings'])
    with SessionLocal() as db:
        db.get(Task,task['id']).applicable_vehicle_types=['仅指定的其它车型'];db.commit()
    response=client.post(f'/api/projects/{pid}/weekly-plans',headers=pm_headers,json={'task_id':task['id'],'week_start':'2001-01-15','scope':{'vehicle_unit_ids':[units[0]]}})
    assert response.status_code==400


def test_plan_completion_rechecks_exact_required_and_safety_checks(client,pm_headers):
    pid,units,ph,task=setup(client,pm_headers,vehicle=True)
    row=create_cell(client,pm_headers,pid,task,mode='finish',target_count=2)
    assert publish(client,pm_headers,pid,row).status_code==200
    with SessionLocal() as db:
        legacy=CheckItem(task_id=task['id'],project_id=None,name='原必需待检',is_required=True,is_safety_critical=True,is_done=False)
        db.add(legacy)
        for uid in units:db.add(VehicleProgress(project_id=pid,vehicle_unit_id=uid,step_key='arrival_inspection',is_done=True,done_on=date(2001,1,3)))
        db.get(Task,task['id']).manually_completed=True;db.get(Task,task['id']).manual_completed_reason='不能覆盖安全';db.commit();cid=legacy.id
    path=f'/api/projects/{pid}/weekly-plans?week_start=2001-01-01&weeks=1'
    facts=client.get(path,headers=pm_headers).json()['cells'][0]['completion']
    assert facts['completed_count']==0 and facts['overdue']
    with SessionLocal() as db:
        from uuid import uuid4
        from app.services.vehicle_checks import snapshot_definitions, generate_for_units
        db.get(CheckItem,cid).is_done=True
        definition=CheckItem(id=str(uuid4()),name='该车必检',is_required=True,is_safety_critical=True,is_done=False,version=0)
        current=db.get(Task,task['id']);snapshot_definitions(db,current,[definition])
        generate_for_units(db,pid,[db.get(VehicleUnit,units[0])],current)
        db.commit();exact_id=db.query(CheckItem).filter_by(task_id=task['id'],vehicle_unit_id=units[0]).one().id
    facts=client.get(path,headers=pm_headers).json()['cells'][0]['completion'];assert facts['completed_count']==1 and not facts['is_complete']
    with SessionLocal() as db:db.get(CheckItem,exact_id).is_done=True;db.commit()
    facts=client.get(path,headers=pm_headers).json()['cells'][0]['completion'];assert facts['completed_count']==2 and facts['is_complete']


def test_unknown_identity_credit_keeps_known_count_without_claiming_actual_date(client,pm_headers):
    pid,units,ph,task=setup(client,pm_headers,vehicle=True)
    with SessionLocal() as db:
        for uid in units:db.delete(db.get(VehicleUnit,uid))
        step=db.query(ProjectVehicleStep).filter_by(project_id=pid,key='arrival_inspection').one();step.expected_quantity=2
        db.add(VehicleProgressMigration(project_id=pid,step_key=step.key,total_count=2,unassigned_count=2,source_metadata={'original_sum':2}))
        db.commit()
    row=create_cell(client,pm_headers,pid,task,mode='finish',target_count=2)
    assert publish(client,pm_headers,pid,row).status_code==200
    facts=client.get(f'/api/projects/{pid}/weekly-plans?week_start=2001-01-01&weeks=1',headers=pm_headers).json()['cells'][0]['completion']
    assert facts['is_complete'] and facts['unidentified_completed']==2 and not facts['quantity_unknown']
    assert facts['actual_dates']==[] and facts['completion_date_unknown'] and facts['warnings']


def test_repair_draft_is_visible_to_planner_without_changing_actual_handler(client,pm_headers,worker_headers):
    pid,units,ph,task=setup(client,pm_headers)
    with SessionLocal() as db:
        worker=db.query(User).filter_by(username='worker1').one();wid=worker.id
        db.get(Project,pid).members=[wid];db.commit()
    base=f'/api/projects/{pid}/vehicle-units/{units[0]}'
    event=client.post(base+'/events',headers=pm_headers,json={'event_type':'fault','event_date':'2001-01-03','title':'现场故障','handler':'实际原处理人'}).json();eid=event['id']
    response=client.post(base+f'/events/{eid}/weekly-plans',headers=pm_headers,json={'week_start':'2001-01-01','assignee_ids':[wid],'mode':'finish','notes':'明确维修安排'})
    assert response.status_code==200,response.text
    row=response.json()['cell'];assert not row['published']
    def read(headers):return next(e for e in client.get(base,headers=headers).json()['events'] if e['id']==eid)
    assert read(pm_headers)['weekly_assignments'][0]['id']==row['id']
    assert read(worker_headers)['weekly_assignments']==[]
    assert publish(client,pm_headers,pid,row).status_code==200
    assert read(worker_headers)['weekly_assignments'][0]['published']
    assert client.post(base+f'/events/{eid}/schedule',headers=pm_headers,json={}).status_code==410
    with SessionLocal() as db:
        original=db.get(VehicleLifecycleEvent,eid);assert original.handler=='实际原处理人' and not original.is_closed
        work=db.get(Task,row['task_id']);assert work.source_vehicle_event_id==eid and not work.manually_completed and work.target_quantity is None


def test_retention_keeps_full_weekly_row_and_publish_retry_is_idempotent(client,pm_headers,worker_headers):
    from app.services.project_retention import project_retention_snapshot
    pid,units,ph,task=setup(client,pm_headers)
    with SessionLocal() as db:
        worker=db.query(User).filter_by(username='worker1').one();wid=worker.id
        db.get(Project,pid).members=[wid];db.commit()
    row=create_cell(client,pm_headers,pid,task,assignee_ids=[wid],notes='原周计划完整说明')
    assert publish(client,pm_headers,pid,row).json()['count']==1
    assert publish(client,pm_headers,pid,{**row,'version':1}).json()['count']==0
    with SessionLocal() as db:
        assert db.query(Notification).filter_by(user_id=wid,project_id=pid,ntype='schedule_confirmed').count()==1
        retained=project_retention_snapshot(db,db.get(Project,pid))['records']['weekly_plan_cells'][0]
        assert retained['notes']=='原周计划完整说明' and retained['assignee_ids']==[wid] and retained['published'] and retained['version']==1
        assert set(retained)=={column.name for column in WeeklyPlanCell.__table__.columns}


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
        actor.permission_overrides={'project.manage_schedule':False};actor.permission_version+=1;first.flush()
        future=pool.submit(attempt);assert entered.wait(2);assert not future.done();first.commit();assert future.result(timeout=10)==403
    with SessionLocal() as db:assert db.query(WeeklyPlanCell).filter_by(project_id=pid).count()==0


def test_pg_concurrent_explicit_claim_has_exactly_one_winner(client,pm_headers):
    if engine.dialect.name!='postgresql':pytest.skip('真实PG双会话认领CAS探针')
    from app.services import weekly_plans
    pid,units,ph,task=setup(client,pm_headers)
    with SessionLocal() as db:
        worker=db.query(User).filter_by(username='worker1').one();db.get(Project,pid).members=[worker.id];db.commit()
    row=create_cell(client,pm_headers,pid,task);assert publish(client,pm_headers,pid,row).status_code==200
    barrier=Barrier(2)
    def attempt(username):
        with SessionLocal() as db:
            actor=db.query(User).filter_by(username=username).one();p=db.get(Project,pid);barrier.wait(timeout=5)
            try:weekly_plans.claim(db,p,actor,row['id'],1)
            except HTTPException as exc:db.rollback();return exc.status_code
            db.commit();return 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(attempt,username) for username in ['worker1','pm']]
        assert sorted(f.result(timeout=15) for f in futures)==[200,409]
    with SessionLocal() as db:
        result=db.get(WeeklyPlanCell,row['id']);assert result.version==2 and len(result.assignee_ids)==1


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


@pytest.mark.parametrize('vehicle',[False,True])
def test_unknown_legacy_intent_cannot_be_completed_overdue_or_silently_cleared(client,pm_headers,vehicle):
    from copy import deepcopy
    from app.models import ChangeLog
    from tests.test_vehicle_progress import write
    pid,units,ph,task=setup(client,pm_headers,vehicle=vehicle)
    if vehicle:assert write(client,pm_headers,pid,units).status_code==200
    with SessionLocal() as db:
        if not vehicle:db.get(Task,task['id']).manually_completed=True
        source={'kind':'t40_legacy_daily_rollup','original_entries':[{'id':'unknown-original','planned_quantity':None}],
            'original_entry_ids':['unknown-original'],'original_planned_sum':None,'known_planned_sum':'1.0',
            'unknown_quantity_count':1,'null_quantity_count':1,'invalid_quantity_count':0,'migration_review_required':True}
        row=WeeklyPlanCell(project_id=pid,task_id=task['id'],scope_key='all:legacy:published:active',scope={'vehicle_unit_ids':[]},
            vehicle_step_key=task['vehicle_step_key'],week_start=date(2001,1,1),mode='finish',target_count=None,
            assignee_ids=[],published=True,source_metadata=source,intent_review_required=True)
        db.add(row);db.commit();cid=row.id
    path=f'/api/projects/{pid}/weekly-plans'
    initial=next(c for c in client.get(path+'?week_start=2001-01-01&weeks=1',headers=pm_headers).json()['cells'] if c['id']==cid)
    assert initial['intent_review_required'] and initial['completion']['state']=='unknown'
    assert not initial['completion']['is_complete'] and not initial['completion']['overdue']
    assert initial['completion']['completed_count']==(2 if vehicle else 1)
    notes=client.put(path+'/'+cid,headers=pm_headers,json={'version':0,'notes':'仅补说明不核对计划'})
    assert notes.status_code==200 and notes.json()['intent_review_required']
    target={'mode':'finish','target_count':2 if vehicle else None}
    assert client.put(path+'/'+cid,headers=pm_headers,json={'version':1,**target}).status_code==400
    assert client.put(path+'/'+cid,headers=pm_headers,json={'version':1,'confirm_intent':True,**target}).status_code==400
    assert client.put(path+'/'+cid,headers=pm_headers,json={'version':1,'confirm_intent':'true','reason':'不能用字符串确认',**target}).status_code==422
    changed=client.put(path+'/'+cid,headers=pm_headers,json={'version':1,'confirm_intent':True,'reason':'已核对原计划：本周明确完成当前工作',**target})
    assert changed.status_code==200,changed.text
    assert not changed.json()['intent_review_required'] and changed.json()['completion']['is_complete']
    assert changed.json()['source_metadata']==source
    assert client.put(path+'/'+cid,headers=pm_headers,json={'version':1,'confirm_intent':True,'reason':'迟到旧表单',**target}).status_code==409
    with SessionLocal() as db:
        audit=db.query(ChangeLog).filter_by(entity_id=cid,action='update').order_by(ChangeLog.created_at.desc()).first()
        assert audit.old_value['intent_review_required'] and not audit.new_value['intent_review_required']
        assert '已核对原计划' in audit.detail
        assert db.get(Task,task['id']).manually_completed is (not vehicle)


def test_unknown_draft_requires_review_to_publish_and_can_choose_no_quota(client,pm_headers):
    pid,units,ph,task=setup(client,pm_headers)
    with SessionLocal() as db:
        row=WeeklyPlanCell(project_id=pid,task_id=task['id'],scope_key='all:legacy:draft:active',scope={'vehicle_unit_ids':[]},
            week_start=date(2001,1,1),mode='finish',target_count=None,assignee_ids=[],published=False,
            source_metadata={'kind':'t40_legacy_daily_rollup','unknown_quantity_count':1},intent_review_required=True)
        db.add(row);db.commit();cid=row.id
    assert publish(client,pm_headers,pid,{'id':cid,'version':0}).status_code==400
    response=client.put(f'/api/projects/{pid}/weekly-plans/{cid}',headers=pm_headers,
        json={'version':0,'mode':'in_progress','target_count':None,'confirm_intent':True,'reason':'原量未知，现明确只跟进不设完成承诺'})
    assert response.status_code==200,response.text
    assert response.json()['mode']=='in_progress' and not response.json()['intent_review_required']
    assert publish(client,pm_headers,pid,response.json()).status_code==200
    row=client.get(f'/api/projects/{pid}/weekly-plans?week_start=2001-01-01&weeks=1',headers=pm_headers).json()['cells'][0]
    assert not row['completion']['overdue'] and row['target_count'] is None
