"""T32 exact real identity, safe matrix gates and portable fresh qualification."""
from tests.lifecycle_helpers import versioned
from datetime import date
from app.time_utils import project_today
from uuid import uuid4
from app.db import SessionLocal
from app.models import Task, Phase, Module, CheckItem, VehicleCheckDefinition, VehicleUnit, VehicleProgress, ChangeLog, Project
from app.services.vehicle_checks import snapshot_definitions, generate_for_units
from tests.test_vehicle_progress import setup_fleet, write


def work(pid, ids, *, key='arrival_inspection', safety=True, legacy=False, types=None):
    with SessionLocal() as db:
        p=Phase(project_id=pid,name='检查工作',sort_order=100);db.add(p);db.flush()
        m=Module(project_id=pid,phase_id=p.id,name='逐车检查');db.add(m);db.flush()
        t=Task(project_id=pid,module_id=m.id,name='实车检查',quantity_type='per_vehicle',target_quantity=len(ids),vehicle_step_key=key,applicable_vehicle_types=types or [])
        db.add(t);db.flush()
        c=CheckItem(id=str(uuid4()),task_id=t.id,project_id=pid,name='急停测试',is_required=True,is_safety_critical=safety,version=0)
        if legacy:db.add(c);db.flush()
        snapshot_definitions(db,t,[c])
        if not legacy:generate_for_units(db,pid,[db.get(VehicleUnit,i) for i in ids],t)
        db.commit();return t.id


def checks(c,h,pid,uid,key=None):
    r=c.get(f'/api/projects/{pid}/vehicle-units/{uid}/checks',headers=h,params={'step_key':key} if key else {})
    assert r.status_code==200,r.text
    return r.json()['items']


def mark(c,h,pid,row,**state):
    return c.put(f"/api/projects/{pid}/check-items/{row['id']}",headers=h,json={'version':row['version'],**state})


def test_safety_is_exact_car_step_atomic_and_never_na_or_manual_cover(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,2);tid=work(pid,ids)
    a,b=[checks(client,pm_headers,pid,i)[0] for i in ids]
    assert a['id']!=b['id'] and a['vehicle_unit_id']==ids[0]
    assert mark(client,pm_headers,pid,a,is_applicable=False,not_applicable_reason='不想查').status_code==400
    assert mark(client,pm_headers,pid,a,is_done=True).status_code==200
    with SessionLocal() as db:
        t=db.get(Task,tid);t.manually_completed=True;t.manual_completed_reason='直接完成';t.manual_check_overrides=[{'check_id':b['id'],'version':0,'failed_reason':''}];db.commit()
    r=write(client,pm_headers,pid,ids)
    assert r.status_code==400 and r.json()['detail']['blockers'][0]['vehicle_unit_id']==ids[1]
    with SessionLocal() as db:assert db.query(VehicleProgress).filter_by(project_id=pid).count()==0
    assert write(client,pm_headers,pid,[ids[1]],key='go_live').status_code==200
    assert mark(client,pm_headers,pid,b,is_done=True).status_code==200
    assert write(client,pm_headers,pid,ids).status_code==200
    assert mark(client,pm_headers,pid,a,is_done=False).status_code==409


def test_pending_never_covered_failed_only_exact_current_snapshot(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,2);tid=work(pid,ids,safety=False)
    rows=[checks(client,pm_headers,pid,i)[0] for i in ids]
    with SessionLocal() as db:version=db.get(Task,tid).version or 0
    blocked=client.put(f'/api/projects/{pid}/work-items/{tid}/completion',headers=pm_headers,json={'version':version,'is_completed':True,'reason':'不能跳过待检'})
    assert blocked.status_code==400 and '车辆进度' in blocked.json()['detail']
    with SessionLocal() as db:
        t=db.get(Task,tid);t.manually_completed=True;t.manual_completed_reason='普通检查明确原因';db.commit()
    assert write(client,pm_headers,pid,[ids[0]]).status_code==400
    from app.services.progress import project_completion_blocker_tasks
    with SessionLocal() as db:assert tid in {t.id for t in project_completion_blocker_tasks(db,pid)}
    for row in rows:assert mark(client,pm_headers,pid,row,failed=True,failed_reason='现场条件未满足').status_code==200
    with SessionLocal() as db:
        t=db.get(Task,tid);t.manual_check_overrides=[{'check_id':rows[0]['id'],'version':1,'failed_reason':'现场条件未满足'}];db.commit()
    assert write(client,pm_headers,pid,[ids[0]]).status_code==200
    assert write(client,pm_headers,pid,[ids[1]]).status_code==400
    row=checks(client,pm_headers,pid,ids[0])[0]
    assert mark(client,pm_headers,pid,row,failed=True,failed_reason='新的失败原因').status_code==200
    assert write(client,pm_headers,pid,[ids[0]],version=1).status_code==400


def test_new_unit_pending_legacy_facts_unchanged_explicit_review_idempotent(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);tid=work(pid,ids,legacy=True)
    with SessionLocal() as db:
        c=db.query(CheckItem).filter_by(task_id=tid).one();c.is_done=True;c.done_by='original-actor';db.commit()
    assert checks(client,pm_headers,pid,ids[0])[0]['scope']=='legacy_task'
    assert write(client,pm_headers,pid,ids).status_code==200
    r=client.post(f'/api/projects/{pid}/vehicle-units',headers=pm_headers,json={'asset_code':'REAL-NEW'})
    assert r.status_code==200,r.text
    new=r.json()['id'];actual=next(x for x in checks(client,pm_headers,pid,new) if x['scope']=='vehicle')
    assert not actual['is_done'] and not actual['failed'] and actual['done_by'] is None and actual['done_at'] is None
    assert actual['definition_version']==1 and actual['vehicle_step_key']=='arrival_inspection'
    assert write(client,pm_headers,pid,[new]).status_code==400
    url=f'/api/projects/{pid}/tasks/{tid}/vehicle-checks/generate'
    assert client.post(url,headers=pm_headers,json={'vehicle_unit_ids':ids,'reason':' '}).status_code==400
    assert client.post(url,headers=pm_headers,json={'vehicle_unit_ids':ids,'reason':'存量实车复核'}).json()['created']==1
    assert client.post(url,headers=pm_headers,json={'vehicle_unit_ids':ids,'reason':'幂等核对'}).json()['created']==0
    with SessionLocal() as db:
        assert db.query(CheckItem).filter_by(task_id=tid,vehicle_unit_id=None).one().is_done
        assert db.query(ChangeLog).filter_by(project_id=pid,entity_type='vehicle_check',action='generate_review').count()==2


def test_real_step_link_required_qualified_facts_cannot_rebind(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);tid=work(pid,ids,key=None)
    row=checks(client,pm_headers,pid,ids[0])[0]
    assert mark(client,pm_headers,pid,row,is_done=True).status_code==400
    assert write(client,pm_headers,pid,ids,key='go_live').status_code==400
    url=f'/api/projects/{pid}/tasks/{tid}'
    assert client.put(url,headers=pm_headers,json=versioned(tid, {'vehicle_step_key':'not_this_project'}, 'Task')).status_code==400
    r=client.put(url,headers=pm_headers,json={'vehicle_step_key':'arrival_inspection','version':0})
    assert r.status_code==200 and r.json()['vehicle_step_key']=='arrival_inspection',r.text
    assert mark(client,pm_headers,pid,checks(client,pm_headers,pid,ids[0])[0],is_done=True).status_code==200
    assert client.put(url,headers=pm_headers,json={'vehicle_step_key':'go_live','version':1}).status_code==400


def test_legacy_null_safety_still_gates_exact_step(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);tid=work(pid,ids,legacy=True)
    row=checks(client,pm_headers,pid,ids[0])[0]
    assert row['vehicle_unit_id'] is None and row['scope']=='legacy_task'
    assert write(client,pm_headers,pid,ids).status_code==400
    assert mark(client,pm_headers,pid,row,is_done=True).status_code==200
    assert write(client,pm_headers,pid,ids).status_code==200
    with SessionLocal() as db:assert db.query(CheckItem).filter_by(task_id=tid,vehicle_unit_id=None).count()==1


def test_permission_state_and_acceptance_scope(client,pm_headers,worker_headers):
    from app.services.acceptance import acceptance_scope_fingerprint
    pid,ids=setup_fleet(client,pm_headers,1);work(pid,ids)
    row=checks(client,pm_headers,pid,ids[0])[0]
    other,otherids=setup_fleet(client,pm_headers,1)
    assert client.get(f'/api/projects/{pid}/vehicle-units/{otherids[0]}/checks',headers=pm_headers).status_code==404
    assert mark(client,worker_headers,pid,row,is_done=True).status_code==404
    with SessionLocal() as db:
        fingerprint=acceptance_scope_fingerprint(db,pid);p=db.get(Project,pid);p.status='ready';db.commit()
    assert mark(client,pm_headers,pid,row,is_done=True).status_code==400
    with SessionLocal() as db:p=db.get(Project,pid);p.status='executing';db.commit()
    assert mark(client,pm_headers,pid,row,is_done=True).status_code==200
    with SessionLocal() as db:
        assert acceptance_scope_fingerprint(db,pid)==fingerprint
        u=VehicleUnit(project_id=pid,asset_code='new-scoped-real');db.add(u);db.flush();generate_for_units(db,pid,[u]);db.commit()
        assert acceptance_scope_fingerprint(db,pid)!=fingerprint


def test_portable_and_clone_only_requirements_no_qualification(client,pm_headers):
    from app.services.import_export import project_to_json
    from app.services.project_retention import project_retention_snapshot
    pid,ids=setup_fleet(client,pm_headers,2);tid=work(pid,ids)
    for uid in ids:assert mark(client,pm_headers,pid,checks(client,pm_headers,pid,uid)[0],is_done=True).status_code==200
    with SessionLocal() as db:
        from app.models import User
        payload=project_to_json(db,pid,actor=db.get(User,db.get(Project,pid).manager))
        definition=next(t for m in payload['modules'] for t in m['tasks'] if t['source_id']==tid)
        assert len(definition['check_items'])==1
        retained=project_retention_snapshot(db,db.get(Project,pid))
        assert len(retained['records']['vehicle_check_definitions'])==1
    definition['check_items'][0]['acceptance_standard']='急停距离须满足现场验收值'
    definition['check_items'][0]['evidence_required']='保留逐车实测录像'
    payload['project']['name']='重新验证导入';payload['project']['status']='preparing'
    r=client.post('/api/projects/import/json',headers=pm_headers,json=payload)
    assert r.status_code==200,r.text
    with SessionLocal() as db:
        actual=db.query(CheckItem).filter_by(project_id=r.json()['id']).all()
        assert len(actual)==2 and all(c.vehicle_unit_id and not c.is_done and not c.failed and c.done_at is None for c in actual)
        assert all('验收标准：急停距离须满足现场验收值' in c.description and '证据要求：保留逐车实测录像' in c.description for c in actual)
        frozen=db.query(VehicleCheckDefinition).filter_by(project_id=r.json()['id']).one()
        assert '保留逐车实测录像' in frozen.description
        assert db.query(CheckItem).filter_by(project_id=pid,is_done=True).count()==2
    r=client.post(f'/api/projects/{pid}/clone',headers=pm_headers,json={'name':'重新验证克隆'})
    assert r.status_code==200,r.text
    with SessionLocal() as db:
        clone=r.json()['id']
        assert db.query(VehicleUnit).filter_by(project_id=clone).count()==0
        assert db.query(CheckItem).filter_by(project_id=clone).count()==0
        assert db.query(VehicleCheckDefinition).filter_by(project_id=clone).count()==1


def test_template_mapping_copy_and_generation_reset_all_source_qualification(client,admin_headers,pm_headers):
    from app.models import Template
    from app.routers.templates import copy_tree
    pid,ids=setup_fleet(client,pm_headers,2)
    with SessionLocal() as db:
        source=db.query(Task).join(Module,Task.module_id==Module.id).join(Phase,Module.phase_id==Phase.id).filter(
            Task.project_id.is_(None),Task.template_id.is_(None),Task.quantity_type=='per_vehicle',Phase.name!='项目准备').first()
        assert source is not None
        source.vehicle_step_key='arrival_inspection'
        check=db.query(CheckItem).filter_by(task_id=source.id).first()
        if check is None:check=CheckItem(task_id=source.id,name='模板定义',is_required=True,is_safety_critical=True);db.add(check)
        check.is_done=True;check.failed=False;check.done_by='source-actor';check.version=19
        db.commit();source_id=source.id;mid=source.module_id;check_id=check.id
        dest=Template(name='逐车检查模板副本');db.add(dest);db.flush()
        copy_tree(db,'default',dest.id)
        db.commit()
        copied=db.query(Task).filter_by(template_id=dest.id,name=source.name).first()
        assert copied.vehicle_step_key=='arrival_inspection'
        assert all(not c.is_done and not c.failed and c.done_by is None and c.done_at is None for c in db.query(CheckItem).filter_by(task_id=copied.id))
    r=client.post(f'/api/projects/{pid}/tasks/generate',headers=pm_headers,json={'module_ids':[mid]})
    assert r.status_code==200,r.text
    with SessionLocal() as db:
        target=db.query(Task).filter_by(project_id=pid,source_task_id=source_id).one()
        assert target.vehicle_step_key=='arrival_inspection'
        definition=db.query(VehicleCheckDefinition).filter_by(task_id=target.id,source_check_id=check_id).one()
        assert definition.source_version==19
        items=db.query(CheckItem).filter_by(task_id=target.id,vehicle_check_definition_id=definition.id).all()
        assert {x.vehicle_unit_id for x in items}==set(ids)
        assert all(not x.is_done and not x.failed and x.done_by is None and x.done_at is None and x.version==0 for x in items)
        assert db.query(CheckItem).filter_by(task_id=target.id,vehicle_unit_id=None).count()==0
    assert client.put('/api/templates/default/vehicle-steps',headers=admin_headers,json={'steps':[{'key':'other_step','name':'其它环节'}]}).status_code==400


def test_project_lock_prevents_stale_pass_from_qualifying_matrix(client,pm_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi import HTTPException
    from app.db import engine
    import pytest
    if engine.dialect.name!='postgresql':pytest.skip('真实PostgreSQL双会话串行验证')
    from app.models import User
    from app.routers.vehicle_progress import change_matrix,MatrixChange
    from app.services.record_lock import lock_writable_project
    pid,ids=setup_fleet(client,pm_headers,1);tid=work(pid,ids)
    row=checks(client,pm_headers,pid,ids[0])[0]
    assert mark(client,pm_headers,pid,row,is_done=True).status_code==200
    entered=Event()
    def attempt():
        with SessionLocal() as db:
            actor=db.query(User).filter_by(username='pm').one();entered.set()
            try:
                change_matrix(pid,MatrixChange(cells=[{'vehicle_unit_id':ids[0],'step_key':'arrival_inspection','version':0}],is_done=True,done_on=project_today('Asia/Shanghai')),actor,db)
            except HTTPException as exc:db.rollback();return exc.status_code
        return 200
    with SessionLocal() as first,ThreadPoolExecutor(max_workers=1) as pool:
        actor=first.query(User).filter_by(username='pm').one();lock_writable_project(first,first.get(Project,pid),actor)
        ci=first.get(CheckItem,row['id']);ci.is_done=False;ci.done_by=None;ci.done_at=None;ci.version+=1;first.flush()
        future=pool.submit(attempt);assert entered.wait(2)
        assert not future.done()
        first.commit()
        assert future.result(timeout=10)==400
    with SessionLocal() as db:assert db.query(VehicleProgress).filter_by(project_id=pid).count()==0


def test_source_definition_version_and_check_cas_cannot_be_bypassed(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);tid=work(pid,ids)
    row=checks(client,pm_headers,pid,ids[0])[0]
    assert client.put(f"/api/projects/{pid}/check-items/{row['id']}",headers=pm_headers,json={'is_done':True}).status_code==400
    assert client.put(f'/api/projects/{pid}/tasks/{tid}',headers=pm_headers,json={'vehicle_step_key':'go_live'}).status_code==428
    assert mark(client,pm_headers,pid,row,is_done=True).status_code==200
    rebind=client.put(f'/api/projects/{pid}/tasks/{tid}',headers=pm_headers,json=versioned(tid, {'vehicle_step_key':'go_live'}, 'Task'))
    assert rebind.status_code==400 and '检查事实' in rebind.json()['detail']
    with SessionLocal() as db:
        definition=db.query(VehicleCheckDefinition).filter_by(task_id=tid).one();definition.version=2;db.commit()
    assert write(client,pm_headers,pid,ids).status_code==400
    current=checks(client,pm_headers,pid,ids[0])[0]
    assert '来源版本' in current['blocker']
    assert mark(client,pm_headers,pid,current,is_done=True).status_code==400


def test_type_change_adds_only_newly_applicable_safety_checks(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1)
    from app.models import VehicleType
    with SessionLocal() as db:
        target_type=db.query(VehicleType).filter(VehicleType.is_enabled.is_(True),VehicleType.name!='潜伏式').first().name
    tid=work(pid,ids,types=[target_type]);legacy=work(pid,ids,legacy=True)
    with SessionLocal() as db:
        vid=db.get(VehicleUnit,ids[0]).vehicle_id
        original=db.query(CheckItem).filter_by(task_id=legacy).one();original.is_done=True;db.commit()
        assert db.query(CheckItem).filter_by(task_id=tid).count()==0
        db.get(Task,tid).target_quantity=0;db.commit()
    r=client.put(f'/api/projects/{pid}/vehicles/{vid}',headers=pm_headers,json={'vehicle_type':target_type})
    assert r.status_code==200,r.text
    row=next(c for c in checks(client,pm_headers,pid,ids[0]) if c['task_id']==tid)
    assert row['vehicle_unit_id']==ids[0] and not row['is_done'] and row['is_safety_critical']
    assert write(client,pm_headers,pid,ids).status_code==400
    with SessionLocal() as db:
        assert db.query(CheckItem).filter_by(task_id=legacy,vehicle_unit_id=None).one().is_done
        assert db.query(CheckItem).filter(CheckItem.task_id==legacy,CheckItem.vehicle_unit_id.isnot(None)).count()==0
        assert db.query(ChangeLog).filter_by(project_id=pid,action='generate_scope').count()==1
        assert db.get(Task,tid).target_quantity==1
    assert mark(client,pm_headers,pid,row,is_done=True).status_code==200
    assert write(client,pm_headers,pid,ids).status_code==200


def test_deleted_type_cannot_prove_real_unit_exempt_from_safety(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);tid=work(pid,ids,types=['叉车式'])
    with SessionLocal() as db:vid=db.get(VehicleUnit,ids[0]).vehicle_id
    r=client.delete(f'/api/projects/{pid}/vehicles/{vid}',headers=pm_headers)
    assert r.status_code==200,r.text
    row=next(c for c in checks(client,pm_headers,pid,ids[0]) if c['task_id']==tid)
    assert row['vehicle_unit_id']==ids[0] and not row['is_done']
    assert write(client,pm_headers,pid,ids).status_code==400


def test_retired_preparation_reminders_do_not_gain_vehicle_obligations(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers,1);tid=work(pid,ids,legacy=True)
    with SessionLocal() as db:
        task=db.get(Task,tid);module=db.get(Module,task.module_id);db.get(Phase,module.phase_id).name='项目准备';db.commit()
    assert client.put(f'/api/projects/{pid}/tasks/{tid}',headers=pm_headers,json={'vehicle_step_key':'arrival_inspection','version':0}).status_code==400
    assert checks(client,pm_headers,pid,ids[0])==[]
    r=client.post(f'/api/projects/{pid}/vehicle-units',headers=pm_headers,json={'asset_code':'REAL-NEW-SCOPE'})
    assert r.status_code==200,r.text
    with SessionLocal() as db:
        rows=db.query(CheckItem).filter_by(task_id=tid).all()
        assert len(rows)==1 and rows[0].vehicle_unit_id is None and not rows[0].is_done
    assert write(client,pm_headers,pid,ids).status_code==200
