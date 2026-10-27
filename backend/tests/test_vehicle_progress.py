"""T30 real identities, atomic matrices, provenance and equal-weight progress."""
from datetime import timedelta
import pytest
from app.time_utils import project_today
from tests.test_project_events import fleet, unit


def setup_fleet(client,headers,n=2,status='executing'):
    from app.db import SessionLocal
    from app.models import Project
    p,vid=fleet(client,headers,n)
    ids=[unit(client,headers,p['id'],vid,f'AGV-{i+1:03}') for i in range(n)]
    with SessionLocal() as db:
        row=db.get(Project,p['id']);row.status=status;db.commit()
    return p['id'],ids


def matrix(client,h,pid):
    r=client.get(f'/api/projects/{pid}/vehicle-progress',headers=h)
    assert r.status_code==200,r.text
    return r.json()


def write(client,h,pid,ids,key='arrival_inspection',version=0,**extra):
    return client.put(f'/api/projects/{pid}/vehicle-progress',headers=h,json={
        'cells':[{'vehicle_unit_id':i,'step_key':key,'version':version} for i in ids],
        'is_done':True,'done_on':project_today('Asia/Shanghai').isoformat(),**extra})


def test_25_by_5_batch_and_cancel_is_audited_without_state_change(client,pm_headers):
    from app.db import SessionLocal
    from app.models import Project,VehicleUnit,VehicleProgress,ChangeLog
    pid,ids=setup_fleet(client,pm_headers,25)
    data=matrix(client,pm_headers,pid)
    assert len(data['steps'])==5 and len(data['units'])==25 and data['summary']['target']==125
    for key in [s['key'] for s in data['steps']]:
        r=write(client,pm_headers,pid,ids,key=key)
        assert r.status_code==200,r.text
    assert r.json()['summary']['completed']==125 and r.json()['summary']['percent']==100
    assert write(client,pm_headers,pid,[ids[0]],key='go_live',version=1,is_done=False,done_on=None).status_code==400
    r=write(client,pm_headers,pid,[ids[0]],key='go_live',version=1,is_done=False,done_on=None,reason='复测发现需重做')
    assert r.status_code==200 and r.json()['summary']['completed']==124
    with SessionLocal() as db:
        assert db.get(Project,pid).status=='executing'
        assert db.get(VehicleUnit,ids[0]).current_stage=='system_integration'
        assert db.query(VehicleProgress).filter_by(project_id=pid).count()==125
        assert db.query(ChangeLog).filter_by(project_id=pid,entity_type='vehicle_progress',action='reopen').one().detail.endswith('复测发现需重做')


@pytest.mark.parametrize('status',['preparing','ready','suspended','completed','archived'])
def test_no_matrix_writes_before_execution_or_after_end(client,pm_headers,status):
    pid,ids=setup_fleet(client,pm_headers,1,status)
    r=write(client,pm_headers,pid,ids)
    assert r.status_code==400,r.text
    assert matrix(client,pm_headers,pid)['summary']['completed']==0


@pytest.mark.parametrize('status',['executing','acceptance'])
def test_old_execution_states_allow_recording_without_transition(client,pm_headers,status):
    from app.db import SessionLocal
    from app.models import Project
    pid,ids=setup_fleet(client,pm_headers,1,status)
    assert write(client,pm_headers,pid,ids).status_code==200
    with SessionLocal() as db: assert db.get(Project,pid).status==status


def test_entire_batch_rejects_stale_cell_foreign_vehicle_future_and_duplicates(client,pm_headers):
    pid,ids=setup_fleet(client,pm_headers)
    other,others=setup_fleet(client,pm_headers,1)
    assert write(client,pm_headers,pid,[ids[0]]).status_code==200
    assert write(client,pm_headers,pid,ids).status_code==409
    assert matrix(client,pm_headers,pid)['summary']['completed']==1
    assert write(client,pm_headers,pid,[ids[1],others[0]]).status_code==404
    assert write(client,pm_headers,pid,[ids[1]],done_on=(project_today('Asia/Shanghai')+timedelta(days=1)).isoformat()).status_code==400
    assert write(client,pm_headers,pid,[ids[1],ids[1]]).status_code==400
    assert matrix(client,pm_headers,pid)['summary']['completed']==1


def test_template_steps_are_frozen_and_old_lifecycle_is_independent(client,pm_headers,admin_headers):
    from app.db import SessionLocal
    from app.models import VehicleUnit,VehicleLifecycleEvent
    pid,ids=setup_fleet(client,pm_headers,1)
    # 默认模板工作已关联环节：不能直接删掉被关联的环节。
    r=client.put('/api/templates/default/vehicle-steps',headers=admin_headers,json={'steps':[{'key':'custom','name':'现场自定义环节'}]})
    assert r.status_code==400 and '工作关联' in r.json()['detail']
    current=client.get('/api/templates/default/vehicle-steps',headers=admin_headers).json()
    r=client.put('/api/templates/default/vehicle-steps',headers=admin_headers,json={'steps':current+[{'key':'custom','name':'现场自定义环节'}]})
    assert r.status_code==200,r.text
    assert len(matrix(client,pm_headers,pid)['steps'])==5
    next_pid,next_ids=setup_fleet(client,pm_headers,1)
    assert [s['key'] for s in matrix(client,pm_headers,next_pid)['steps']]==[s['key'] for s in current]+['custom']
    assert write(client,pm_headers,pid,ids,key='go_live').status_code==200
    assert write(client,pm_headers,pid,ids,key='arrival_inspection',done_on=project_today('Asia/Shanghai').isoformat()).status_code==200
    assert client.put(f'/api/projects/{pid}/vehicle-units/{ids[0]}',headers=pm_headers,json={'current_stage':'retired'}).status_code==400
    r=client.post(f'/api/projects/{pid}/vehicle-units/{ids[0]}/events',headers=pm_headers,json={'event_type':'fault','event_date':'2026-01-01','title':'传感器故障原履历','stage_after':'maintenance'})
    assert r.status_code==200,r.text
    with SessionLocal() as db:
        assert db.get(VehicleUnit,ids[0]).current_stage=='go_live'
        assert db.query(VehicleLifecycleEvent).filter_by(vehicle_unit_id=ids[0],event_type='fault').one().stage_after=='maintenance'


def test_unregistered_quantity_does_not_fabricate_real_vehicles(client,pm_headers):
    p,vid=fleet(client,pm_headers,25)
    data=matrix(client,pm_headers,p['id'])
    assert data['units']==[] and data['summary']['target']==125
    assert data['summary']['unregistered_quantity']==25 and not data['summary']['quantity_unknown']
    p2=client.post('/api/projects',headers=pm_headers,json={'name':'数量未知','start_date':'2026-01-01','end_date':'2026-12-31'}).json()
    assert matrix(client,pm_headers,p2['id'])['summary']['quantity_unknown'] is True


def test_worker_membership_system_permission_and_hidden_project(client,pm_headers,worker_headers):
    from app.db import SessionLocal
    from app.models import Project,User
    pid,ids=setup_fleet(client,pm_headers,1)
    assert write(client,worker_headers,pid,ids).status_code==404
    with SessionLocal() as db:
        p=db.get(Project,pid);worker=db.query(User).filter_by(username='worker1').one();p.members=[worker.id];db.commit()
    assert write(client,worker_headers,pid,ids).status_code==200
    with SessionLocal() as db:
        worker=db.query(User).filter_by(username='worker1').one();worker.permission_overrides={'worker.report':False};db.commit()
    assert write(client,worker_headers,pid,ids,key='single_commissioning').status_code==403


def test_progress_ignores_mixed_quantity_weights_and_curve_is_weekly(client,pm_headers):
    from app.db import SessionLocal
    from app.models import Module,Phase,Task,DailyProgress,Project,User
    from app.services.progress import project_progress_tree,plan_vs_actual_timeline
    pid,ids=setup_fleet(client,pm_headers,1)
    assert write(client,pm_headers,pid,ids).status_code==200
    with SessionLocal() as db:
        phase=Phase(project_id=pid,name='实施',sort_order=1);db.add(phase);db.flush()
        module=Module(project_id=pid,phase_id=phase.id,name='普通工作');db.add(module);db.flush()
        t1=Task(project_id=pid,module_id=module.id,name='1000米线路',quantity_type='fixed',unit='米',target_quantity=1000,manually_completed=True)
        t2=Task(project_id=pid,module_id=module.id,name='一次培训',quantity_type='fixed',unit='次',target_quantity=1)
        db.add_all([t1,t2]);db.flush()
        totals=project_progress_tree(db,pid)
        assert totals['target']==7 and totals['completed']==2 and totals['percent']==28.6
        from app.routers.dashboard import _project_progress_totals
        portfolio=_project_progress_totals(db,[t1,t2],[pid])[pid]
        assert (portfolio['target'],portfolio['completed'],portfolio['percent'])==(7,2,28.6)
        timeline=plan_vs_actual_timeline(db,pid,None,None)
        assert all(r['period']=='week' and r['unit']=='车辆环节' for r in timeline)
        assert sum(r['actual'] for r in timeline)==1


def test_adjust_quantity_api_is_retired(client,pm_headers):
    assert client.post('/api/worker/reports/adjust',headers=pm_headers,json={}).status_code==404


def test_portable_matrix_restores_real_vehicle_links_and_clone_has_no_actuals(client,pm_headers):
    from app.db import SessionLocal
    from app.models import Project,VehicleProgress
    from app.services.import_export import project_to_json
    from app.services.vehicle_progress import parse_snapshot
    pid,ids=setup_fleet(client,pm_headers,2)
    assert write(client,pm_headers,pid,[ids[0]]).status_code==200
    with SessionLocal() as db:
        from app.models import User
        snapshot=project_to_json(db,pid,actor=db.get(User,db.get(Project,pid).manager))
        assert parse_snapshot(snapshot)['units'][0]['id'] in ids
    snapshot['project']['status']='preparing'  # portable import keeps the existing fresh-project lifecycle contract
    imported=client.post('/api/projects/import/json',headers=pm_headers,json=snapshot)
    assert imported.status_code==200,imported.text
    target=matrix(client,pm_headers,imported.json()['id'])
    assert target['summary']['completed']==0 and target['source_snapshot_available']
    assert target['units'][0]['id'] not in ids and target['units'][0]['cells']=={}
    source=client.get(f"/api/projects/{imported.json()['id']}/vehicle-progress/source",headers=pm_headers).json()
    assert source['read_only'] and not source['verified']
    assert source['source']['vehicle_progress_matrix']['units'][0]['cells']['arrival_inspection']['done_on']
    assert source['source']['execution_evidence']['vehicle_progress_matrix']['summary']['completed']==1
    clone=client.post(f'/api/projects/{pid}/clone',headers=pm_headers,json={'name':'新现场'})
    assert clone.status_code==200,clone.text
    target=matrix(client,pm_headers,clone.json()['id'])
    assert len(target['steps'])==5 and target['units']==[] and target['summary']['completed']==0
    # Tampered provenance must fail in preview before creating any project.
    snapshot['vehicle_progress_matrix']['units'][0]['id']='foreign-unit'
    with pytest.raises(ValueError,match='真实车辆'):parse_snapshot(snapshot)


def test_same_version_concurrent_writes_never_double_count(client,pm_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from app.db import SessionLocal
    from app.models import User,VehicleProgress
    from app.routers.vehicle_progress import MatrixChange,change_matrix
    pid,ids=setup_fleet(client,pm_headers,1)
    barrier=Barrier(2)
    def apply():
        with SessionLocal() as db:
            user=db.query(User).filter_by(username='pm').one()
            barrier.wait(timeout=10)
            try:
                change_matrix(pid,MatrixChange(cells=[{'vehicle_unit_id':ids[0],'step_key':'arrival_inspection','version':0}],is_done=True,done_on=project_today('Asia/Shanghai')),user,db)
                return 200
            except HTTPException as error:
                db.rollback();return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:apply(),range(2)))
    assert sorted(results)==[200,409]
    with SessionLocal() as db:
        assert db.query(VehicleProgress).filter_by(project_id=pid,is_done=True).count()==1


def test_state_and_membership_are_rechecked_after_waiting_for_project_lock(client,pm_headers,worker_headers,monkeypatch):
    from app.db import SessionLocal
    from app.models import Project,User
    from app.services import field_operations as router
    pid,ids=setup_fleet(client,pm_headers,1)
    original=router.lock_writable_project
    def transition(db,project,user):
        with SessionLocal() as other:
            other.get(Project,pid).status='ready';other.commit()
        return original(db,project,user)
    monkeypatch.setattr(router,'lock_writable_project',transition)
    assert write(client,pm_headers,pid,ids).status_code==400
    assert matrix(client,pm_headers,pid)['summary']['completed']==0


def test_portfolio_weekly_trend_is_retired_and_matrix_reads_cells(client,pm_headers):
    """旧按周数量趋势已退役；车辆环节进度只从逐车格子读取。"""
    pid,ids=setup_fleet(client,pm_headers,1)
    assert write(client,pm_headers,pid,ids).status_code==200
    assert client.get('/api/dashboard/trend',headers=pm_headers).status_code==410
    assert matrix(client,pm_headers,pid)['summary']['completed']==1

