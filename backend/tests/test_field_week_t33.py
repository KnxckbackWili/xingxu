"""T33 actual operators, local dates, immutable corrections and offline replay."""
from datetime import timedelta,date
from concurrent.futures import ThreadPoolExecutor
import uuid
import pytest
from app.db import SessionLocal
from app.models import User,Project,FieldOperation,VehicleProgress,ChangeLog
from app.time_utils import project_today
from tests.test_vehicle_progress import setup_fleet


def prepared(client,pm_headers):
    pid,units=setup_fleet(client,pm_headers,1)
    with SessionLocal() as db:
        people={u.username:u.id for u in db.query(User)}
        p=db.get(Project,pid);p.members=list(set(p.members or [])|{people['worker1'],people['worker2']})
        from app.routers.projects import _sync_project_members
        _sync_project_members(db,p);db.commit()
    return pid,units[0],people


def operation(pid,unit,**extra):
    return {'project_id':pid,'kind':'vehicle','target_id':unit,'step_key':'arrival_inspection','is_done':True,
        'completion_date':project_today('Asia/Shanghai').isoformat(),'reason':'现场真实核对并完成检查','version':0,'client_uuid':str(uuid.uuid4()),**extra}


def save(client,headers,data):return client.post('/api/worker/operations',headers=headers,json=data)


def test_actual_dates_operator_assistance_and_append_only_revision(client,pm_headers,worker_headers):
    pid,unit,people=prepared(client,pm_headers)
    yesterday=(project_today('Asia/Shanghai')-timedelta(days=1)).isoformat()
    body=operation(pid,unit,completion_date=yesterday,assisted_user_id=people['worker2'])
    response=save(client,worker_headers,body);assert response.status_code==200,response.text
    row=response.json();assert row['completion_date']==yesterday and row['actor_id']==people['worker1']
    assert row['assisted_user_id']==people['worker2'] and row['recorded_at'][:10]>=yesterday
    assert response.headers['cache-control']=='private, no-store'
    edit={'version':row['version'],'completion_date':yesterday,'reason':'更正实际记录附注','note':'修订后原件一致','client_uuid':str(uuid.uuid4())}
    changed=client.put('/api/worker/records/'+row['id'],headers=worker_headers,json=edit)
    assert changed.status_code==200,changed.text
    current=changed.json();assert current['action']=='edit' and current['replaces_id']==row['id']
    retract={**edit,'version':current['version'],'reason':'本人核对后撤回这次修订','client_uuid':str(uuid.uuid4())}
    undone=client.request('DELETE','/api/worker/records/'+current['id'],headers=worker_headers,json=retract)
    assert undone.status_code==200,undone.text
    with SessionLocal() as db:
        original=db.get(FieldOperation,row['id']);assert original.completion_date.isoformat()==yesterday and original.note=='现场真实核对并完成检查'
        assert db.query(FieldOperation).filter_by(project_id=pid).count()==3
        assert db.query(ChangeLog).filter_by(project_id=pid,entity_type='field_operation').count()==3
    records=client.get('/api/worker/records',headers=worker_headers).json()['records'];assert len(records)==3
    assert not next(r for r in records if r['id']==row['id'])['can_edit']


@pytest.mark.parametrize('offset',[1,-40])
def test_local_future_and_outside_window_rejected_without_mutation(client,pm_headers,worker_headers,offset):
    pid,unit,_=prepared(client,pm_headers)
    response=save(client,worker_headers,operation(pid,unit,completion_date=(project_today('Asia/Shanghai')+timedelta(days=offset)).isoformat()))
    assert response.status_code==400,response.text
    with SessionLocal() as db:assert db.query(FieldOperation).filter_by(project_id=pid).count()==db.query(VehicleProgress).filter_by(project_id=pid).count()==0


def test_configurable_window_and_project_local_day(client,pm_headers,worker_headers,monkeypatch):
    from app.services import field_operations as service
    pid,unit,_=prepared(client,pm_headers)
    with SessionLocal() as db:db.get(Project,pid).timezone='Pacific/Kiritimati';db.commit()
    monkeypatch.setenv('FIELD_BACKFILL_DAYS','3');monkeypatch.setattr(service,'project_today',lambda tz:date(2026,10,26))
    assert save(client,worker_headers,operation(pid,unit,completion_date='2026-10-23')).status_code==400
    response=save(client,worker_headers,operation(pid,unit,completion_date='2026-10-24'));assert response.status_code==200,response.text


def test_offline_same_uuid_exact_payload_is_once_and_conflicting_replay_rejected(client,pm_headers,worker_headers):
    pid,unit,_=prepared(client,pm_headers);body=operation(pid,unit)
    payload={'ops':[{'type':'field','client_uuid':body['client_uuid'],'payload':body}]}
    for _ in range(2):
        response=client.post('/api/worker/sync',headers=worker_headers,json=payload)
        assert response.status_code==200,response.text
        assert response.json()['accepted']==[body['client_uuid']],response.text
    payload['ops'][0]['payload']={**body,'reason':'不能用同一编号替换原内容'}
    rejected=client.post('/api/worker/sync',headers=worker_headers,json=payload)
    assert rejected.json()['rejected']==[body['client_uuid']]
    with SessionLocal() as db:assert db.query(FieldOperation).filter_by(project_id=pid).count()==1


def test_concurrent_replay_and_other_actor_cannot_modify_or_retract(client,pm_headers,worker_headers):
    pid,unit,people=prepared(client,pm_headers);body=operation(pid,unit)
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(lambda _:save(client,worker_headers,body),range(2)))
    assert [r.status_code for r in responses]==[200,200],[r.text for r in responses]
    record=responses[0].json();second=client.post('/api/auth/login',json={'username':'worker2','password':'worker123'}).json()
    headers={'Authorization':'Bearer '+second['access_token']}
    # A same-state date rewrite is a correction of another operator's fact.
    assert save(client,headers,operation(pid,unit,version=record['version'],completion_date=(project_today('Asia/Shanghai')-timedelta(days=1)).isoformat(),assisted_user_id=people['worker1'])).status_code==403
    revision={'version':record['version'],'completion_date':body['completion_date'],'reason':'越权修改应被拒绝','client_uuid':str(uuid.uuid4())}
    assert client.put('/api/worker/records/'+record['id'],headers=headers,json=revision).status_code==404
    assert client.request('DELETE','/api/worker/records/'+record['id'],headers=headers,json=revision).status_code==404
    with SessionLocal() as db:assert db.query(FieldOperation).filter_by(project_id=pid).count()==1


def test_stale_actor_permission_and_audit_failure_roll_back(client,pm_headers,worker_headers,monkeypatch):
    from app.services import field_operations as service
    from sqlalchemy import update
    pid,unit,people=prepared(client,pm_headers);original=service.lock_writable_project
    def revoke(db,project,user):
        value=original(db,project,user)
        db.execute(update(User).where(User.id==people['worker1']).values(permission_overrides={'worker.report':False}).execution_options(synchronize_session=False));return value
    monkeypatch.setattr(service,'lock_writable_project',revoke)
    assert save(client,worker_headers,operation(pid,unit)).status_code==403
    monkeypatch.setattr(service,'lock_writable_project',original)
    def fail(*args,**kwargs):raise RuntimeError('isolated audit failure')
    monkeypatch.setattr(service,'log_change',fail)
    with pytest.raises(RuntimeError,match='isolated audit failure'):save(client,worker_headers,operation(pid,unit))
    with SessionLocal() as db:assert db.query(FieldOperation).filter_by(project_id=pid).count()==db.query(VehicleProgress).filter_by(project_id=pid).count()==0


def test_visible_personal_records_and_new_statistics_exclude_recycled_project(client,pm_headers,worker_headers):
    pid,unit,_=prepared(client,pm_headers);assert save(client,worker_headers,operation(pid,unit)).status_code==200
    assert client.get('/api/worker/records',headers=worker_headers).json()['records']
    before=client.get('/api/dashboard/statistics',headers=pm_headers);assert before.status_code==200 and before.json()['projects']==1
    p=client.get('/api/projects/'+pid,headers=pm_headers).json()
    result=client.delete('/api/projects/'+pid,headers=pm_headers,params={'version':p['version']});assert result.status_code==200,result.text
    assert client.get('/api/dashboard/statistics',headers=pm_headers).json()['projects']==0
    assert client.get('/api/worker/records',headers=worker_headers).json()['records']==[]
    assert client.get('/api/people/weeks',headers=pm_headers).json()['projects']==[]


@pytest.mark.parametrize('path',['/api/dashboard/workload','/api/dashboard/stats','/api/dashboard/people-plan','/api/dashboard/team-schedule','/api/north-star','/api/worker/overdue'])
def test_replaced_daily_projections_are_authenticated_retired(client,pm_headers,path):
    assert client.get(path,headers=pm_headers).status_code==410
    client.cookies.clear();assert client.get(path).status_code==401


def test_personnel_week_matrix_uses_visible_published_plans_and_hides_peer_reasons(client,pm_headers,worker_headers,admin_headers,monkeypatch):
    from app.services import field_week
    from app.models import UserUnavailability
    pid,unit,people=prepared(client,pm_headers)
    second,_,_=prepared(client,pm_headers)
    hidden=client.post('/api/projects',headers=admin_headers,json={'name':'HIDDEN-PROJECT','start_date':'2026-01-01','end_date':'2026-12-31'}).json()['id']
    start=project_today('Asia/Shanghai');start-=timedelta(days=start.weekday())
    from tests.test_weekly_plans import create_cell,publish
    from tests.test_work_items_t34 import phase,create
    def cell(project,assignees,headers,published=True):
        work=create(client,headers,project,phase(client,headers,project))
        row=create_cell(client,headers,project,work,week_start=start.isoformat(),assignee_ids=assignees)
        if published:assert publish(client,headers,project,row).status_code==200
        return row
    first_cell=cell(pid,[people['worker1'],people['worker2']],pm_headers)
    second_cell=cell(second,[people['worker1']],pm_headers)
    cell(pid,[people['worker1']],pm_headers,False)
    # A hidden project can have the same named people; project visibility still
    # decides whether its plan is in the personnel view.
    with SessionLocal() as db:
        p=db.get(Project,hidden);p.members=[people['worker1']];db.commit()
    hidden_cell=cell(hidden,[people['worker1']],admin_headers)
    with SessionLocal() as db:
        p=db.get(Project,hidden);p.members=[];db.commit()
    with SessionLocal() as db:
        db.get(User,people['worker1']).permission_overrides={'workspace.view':True}
        db.add(UserUnavailability(user_id=people['worker2'],start_date=start,end_date=start+timedelta(days=2),reason='PRIVATE-MEDICAL',note='PRIVATE-NOTE'));db.commit()
    response=client.get('/api/people/weeks',headers=worker_headers)
    assert response.status_code==200,response.text
    assert 'HIDDEN-PROJECT' not in response.text and 'PRIVATE-MEDICAL' not in response.text and 'PRIVATE-NOTE' not in response.text
    first=next(p for p in response.json()['people'] if p['id']==people['worker1'])
    assert {c['id'] for c in first['cells']}=={first_cell['id'],second_cell['id']}
    assert first['conflicts']==[{'week_start':start.isoformat(),'project_ids':sorted([pid,second])}]
    own=client.get('/api/people/weeks?scope=mine',headers=worker_headers).json()
    assert [p['id'] for p in own['people']]==[people['worker1']]


def test_week_and_project_report_use_actual_records_and_t26_visible_documents(client,pm_headers,worker_headers,monkeypatch):
    from app.services import field_week
    from tests.test_confidential_documents_t26 import policy
    from tests.document_helpers import requirement
    from app.models import ProjectDocument
    from app.time_utils import utcnow
    pid,unit,people=prepared(client,pm_headers)
    secret=requirement(client,pm_headers,pid,name='SECRET-WEEK-DOCUMENT')
    assert policy(client,pm_headers,pid,'document',secret).status_code==200
    with SessionLocal() as db:
        row=db.get(ProjectDocument,secret['id']);row.timing_type='after_event';row.timing_event='internal_kickoff';row.due_at=utcnow()+timedelta(hours=1);row.due_is_estimated=False;db.commit()
    monkeypatch.setattr(field_week,'plan_cells',lambda *args,**kwargs:[])
    assert save(client,worker_headers,operation(pid,unit,assisted_user_id=people['worker2'])).status_code==200
    response=client.get('/api/worker/week',headers=worker_headers)
    assert response.status_code==200,response.text
    assert 'SECRET-WEEK-DOCUMENT' not in response.text and response.json()['state']=='ready'
    report=client.get('/api/projects/'+pid+'/report',headers=worker_headers)
    assert report.status_code==200,report.text
    value=report.json();assert value['summary']['actual_records']==1 and value['summary']['vehicle_completions']==1
    assert value['completed_items'][0]['actor_id']==people['worker1'] and value['completed_items'][0]['assisted_user_id']==people['worker2']
    assert 'SECRET-WEEK-DOCUMENT' not in report.text and 'completed_quantity' not in report.text


@pytest.mark.parametrize('state',['failed','not_applicable'])
@pytest.mark.parametrize('action',['edit','retract'])
def test_check_note_revision_preserves_tri_state_and_retraction_restores_original(client,pm_headers,worker_headers,state,action):
    from tests.test_work_items_t34 import phase,create
    from app.models import CheckItem
    pid,_,_=prepared(client,pm_headers)
    work=create(client,pm_headers,pid,phase(client,pm_headers,pid),checks=[{'name':'真实检查'}])
    cid=work['check_items'][0]['id']
    change={'failed':True,'failed_reason':'真实失败不能被备注修订清除'} if state=='failed' else {'is_applicable':False,'not_applicable_reason':'适用范围已明确排除'}
    body=operation(pid,cid,kind='check',step_key='',is_done=False,**change)
    response=save(client,worker_headers,body);assert response.status_code==200,response.text
    row=response.json()
    revision={'version':row['version'],'completion_date':body['completion_date'],'reason':'仅更正记录备注','note':'原检查状态保持不变','client_uuid':str(uuid.uuid4())}
    method='PUT' if action=='edit' else 'DELETE'
    response=client.request(method,'/api/worker/records/'+row['id'],headers=worker_headers,json=revision)
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        check=db.get(CheckItem,cid)
        assert not check.is_done
        assert check.failed is (state=='failed' and action=='edit')
        assert check.is_applicable is not (state=='not_applicable' and action=='edit')
        if state=='failed' and action=='edit':assert check.failed_reason==change['failed_reason']
        if state=='not_applicable' and action=='edit':assert check.not_applicable_reason==change['not_applicable_reason']
        assert db.query(FieldOperation).filter_by(project_id=pid).count()==2


def test_private_backup_purge_and_portable_source_preserve_actual_people_without_new_qualification(client,pm_headers,worker_headers,admin_headers,tmp_path):
    import json
    from tests.test_retention_unification import prepare,purge
    from app.services.project_deletion import backup_zip
    pid,unit,people=prepared(client,pm_headers)
    result=save(client,worker_headers,operation(pid,unit,assisted_user_id=people['worker2']));assert result.status_code==200,result.text
    identity=result.json()['id']
    exported=client.get('/api/projects/'+pid+'/export/json',headers=pm_headers)
    assert exported.status_code==200,exported.text
    payload=exported.json();evidence=payload['field_operation_evidence']
    assert evidence['read_only'] and evidence['verified'] is False
    assert evidence['records'][0]['actor_id']==people['worker1'] and evidence['records'][0]['assisted_user_id']==people['worker2']
    payload['project']['name']='独立来源不授予完成'
    payload['project']['status']='preparing'
    imported=client.post('/api/projects/import/json',headers=pm_headers,json=payload)
    assert imported.status_code==200,imported.text
    imported_id=imported.json()['id']
    with SessionLocal() as db:
        assert db.query(FieldOperation).filter_by(project_id=imported_id).count()==0
        assert db.query(VehicleProgress).filter_by(project_id=imported_id,is_done=True).count()==0
        original=db.get(Project,imported_id).portable_unverified_snapshot['field_operation_evidence']
        assert original['records'][0]['id']==identity
    current=client.get('/api/projects/'+pid,headers=pm_headers).json()
    assert client.delete('/api/projects/'+pid,headers=pm_headers,params={'version':current['version']}).status_code==200
    recycled=client.get('/api/project-recycle-bin/projects/'+pid,headers=admin_headers).json()
    response=prepare(client,admin_headers,recycled);assert response.status_code==200,response.text
    receipt=response.json();download=client.get('/api/project-recycle-bin/backups/'+receipt['backup_id'],headers=admin_headers)
    path=tmp_path/'actual-evidence.agvenc';path.write_bytes(download.content)
    with backup_zip(path) as bundle:
        snapshot=json.loads(bundle.read('project-backup.json'))
        row=next(r for r in snapshot['records']['field_operations'] if r['id']==identity)
        assert row['actor_id']==people['worker1'] and row['assisted_user_id']==people['worker2']
        assert {people['worker1'],people['worker2']}<={person['id'] for person in snapshot['actors']}
    deleted=purge(client,admin_headers,recycled,receipt);assert deleted.status_code==200,deleted.text
    with SessionLocal() as db:
        assert db.get(Project,pid) is None and db.query(FieldOperation).filter_by(project_id=pid).count()==0


@pytest.mark.parametrize('backwards',[False,True])
def test_latest_revision_uses_locked_sequence_when_clock_is_equal_or_moves_back(client,pm_headers,worker_headers,monkeypatch,backwards):
    from app.time_utils import utcnow
    from app.services import field_operations as service
    pid,unit,_=prepared(client,pm_headers)
    now=utcnow();times=iter([now,now-timedelta(seconds=60) if backwards else now])
    identifiers=iter(['ffffffff-ffff-4fff-8fff-ffffffffffff','00000000-0000-4000-8000-000000000000'])
    monkeypatch.setattr(FieldOperation.__table__.c.recorded_at.default,'arg',lambda context:next(times))
    monkeypatch.setattr(FieldOperation.__table__.c.id.default,'arg',lambda context:next(identifiers))
    first=save(client,worker_headers,operation(pid,unit));assert first.status_code==200,first.text
    second=save(client,worker_headers,operation(pid,unit,version=first.json()['version']))
    assert second.status_code==200,second.text
    assert first.json()['version']==second.json()['version']  # same-state canonical no-op
    with SessionLocal() as db:
        rows=db.query(FieldOperation).filter_by(project_id=pid).order_by(FieldOperation.sequence).all()
        assert [r.sequence for r in rows]==[1,2]
        latest=service.latest(db,pid,'vehicle',unit,'arrival_inspection')
        actor=db.get(User,latest.actor_id)
        assert latest.id==second.json()['id'] and service.serialize(db,latest,actor)['can_edit']
        assert not service.serialize(db,rows[0],actor)['can_edit']


def test_expected_account_header_rejects_cross_tab_cookie_identity_before_mutation(client,pm_headers,worker_headers):
    pid,unit,people=prepared(client,pm_headers)
    wrong={**worker_headers,'X-AGV-Expected-Account':people['worker2']}
    assert save(client,wrong,operation(pid,unit)).status_code==401
    assert client.get('/api/worker/records',headers=wrong).status_code==401
    right={**worker_headers,'X-AGV-Expected-Account':people['worker1']}
    assert save(client,right,operation(pid,unit)).status_code==200
    with SessionLocal() as db:assert db.query(FieldOperation).filter_by(project_id=pid).count()==1


@pytest.mark.parametrize('kind',['vehicle','work'])
def test_undo_date_correction_restores_original_fact_and_both_weekly_report_counts(client,pm_headers,worker_headers,monkeypatch,kind):
    from app.services import field_operations as service
    from tests.test_work_items_t34 import phase,create
    monkeypatch.setattr(service,'project_today',lambda tz:date(2026,10,26))
    pid,unit,_=prepared(client,pm_headers)
    target=unit if kind=='vehicle' else create(client,pm_headers,pid,phase(client,pm_headers,pid))['id']
    body=operation(pid,target,kind=kind,step_key='arrival_inspection' if kind=='vehicle' else '',completion_date='2026-10-25',note='原实际说明')
    first=save(client,worker_headers,body);assert first.status_code==200,first.text
    a=first.json();revision={'version':a['version'],'completion_date':'2026-10-26','reason':'更正完成日期','note':'修改后的实际说明','client_uuid':str(uuid.uuid4())}
    changed=client.put('/api/worker/records/'+a['id'],headers=worker_headers,json=revision);assert changed.status_code==200,changed.text
    b=changed.json()
    def counts(day):
        personal=client.get('/api/worker/week-report',headers=worker_headers,params={'week_start':day})
        report=client.get('/api/projects/'+pid+'/report',headers=worker_headers,params={'ref_date':day})
        assert personal.status_code==report.status_code==200
        summary=report.json()['summary']
        return personal.json()['summary']['completed'],summary['vehicle_completions' if kind=='vehicle' else 'completed_work']
    assert counts('2026-10-25')==(0,0) and counts('2026-10-26')==(1,1)
    undo={**revision,'version':b['version'],'reason':'撤回本次日期修订，保留原事实','client_uuid':str(uuid.uuid4())}
    response=client.request('DELETE','/api/worker/records/'+b['id'],headers=worker_headers,json=undo)
    assert response.status_code==200,response.text
    restored=response.json();assert restored['completion_date']=='2026-10-25' and restored['restores_id']==a['id']
    assert restored['effective'] and restored['can_edit'] and not restored['can_retract']
    assert restored['note']=='原实际说明'
    assert counts('2026-10-25')==(1,1) and counts('2026-10-26')==(0,0)
    with SessionLocal() as db:
        if kind=='vehicle':assert db.query(VehicleProgress).filter_by(project_id=pid,vehicle_unit_id=unit).one().done_on==date(2026,10,25)
        assert db.get(FieldOperation,a['id']).completion_date==date(2026,10,25)
        assert db.get(FieldOperation,b['id']).completion_date==date(2026,10,26)


def test_work_annotation_revision_never_refreshes_an_old_failed_check_override(client,pm_headers,worker_headers):
    from tests.test_work_items_t34 import phase,create
    from app.models import CheckItem,Task
    pid,_,_=prepared(client,pm_headers)
    work=create(client,pm_headers,pid,phase(client,pm_headers,pid),checks=[{'name':'普通失败检查'}]);cid=work['check_items'][0]['id']
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=worker_headers,json={'version':0,'failed':True,'failed_reason':'原失败'}).status_code==200
    result=client.put(f"/api/projects/{pid}/work-items/{work['id']}/completion",headers=pm_headers,
        json={'version':0,'is_completed':True,'reason':'负责人明确承担当前失败版本','override_failed':True,'failed_checks':[{'id':cid,'version':1}]})
    assert result.status_code==200,result.text
    with SessionLocal() as db:
        task=db.get(Task,work['id']);snapshot=list(task.manual_check_overrides);registered_at=task.manual_completed_at
        record=db.query(FieldOperation).filter_by(project_id=pid,kind='work',target_id=task.id).one();identity=record.id
    assert client.put(f'/api/projects/{pid}/check-items/{cid}',headers=worker_headers,json={'version':1,'failed':True,'failed_reason':'新版本失败，不得自动覆盖'}).status_code==200
    revision={'version':1,'completion_date':project_today('Asia/Shanghai').isoformat(),'reason':'只更正说明，不产生新的覆盖资格','note':'修订附注','client_uuid':str(uuid.uuid4())}
    response=client.put('/api/worker/records/'+identity,headers=pm_headers,json=revision)
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        task=db.get(Task,work['id']);assert task.manual_check_overrides==snapshot
        assert task.manual_completed_at==registered_at and task.manual_completed_reason=='修订附注'
        assert db.get(CheckItem,cid).version==2


def test_intern_with_explicit_record_permission_uses_same_member_and_check_guards(client,pm_headers):
    from tests.test_work_items_t34 import phase,create
    pid,_,people=prepared(client,pm_headers)
    work=create(client,pm_headers,pid,phase(client,pm_headers,pid),checks=[{'name':'现场检查一'},{'name':'现场检查二'}])
    with SessionLocal() as db:
        worker=db.get(User,people['worker1'])
        intern=User(username='isolated-intern',display_name='现场实习账号',password_hash=worker.password_hash,role='intern',is_active=True,
                    permission_overrides={'worker.report':True})
        db.add(intern);db.flush();identity=intern.id
        project=db.get(Project,pid);project.members=[*(project.members or []),identity]
        from app.routers.projects import _sync_project_members
        _sync_project_members(db,project);db.commit()
    login=client.post('/api/auth/login',json={'username':'isolated-intern','password':'worker123'})
    assert login.status_code==200
    headers={'Authorization':'Bearer '+login.json()['access_token']}
    first,second=[row['id'] for row in work['check_items']]
    assert save(client,headers,operation(pid,first,kind='check',step_key='')).status_code==200
    direct=client.put(f'/api/projects/{pid}/check-items/{second}',headers=headers,json={'version':0,'is_done':True})
    assert direct.status_code==200,direct.text
    with SessionLocal() as db:assert db.query(FieldOperation).filter_by(project_id=pid,actor_id=identity).count()==2
    other,units=setup_fleet(client,pm_headers,1)
    assert save(client,headers,operation(other,units[0])).status_code==404


def test_own_week_permission_is_independent_of_team_workbench_permission(client,pm_headers,worker_headers):
    _,_,people=prepared(client,pm_headers)
    with SessionLocal() as db:
        db.get(User,people['worker1']).permission_overrides={'workspace.view':False,'personal.schedule.read':True};db.commit()
    assert client.get('/api/people/weeks?scope=mine',headers=worker_headers).status_code==200
    assert client.get('/api/people/weeks?scope=team',headers=worker_headers).status_code==403
    with SessionLocal() as db:
        db.get(User,people['worker1']).permission_overrides={'workspace.view':True,'personal.schedule.read':False};db.commit()
    assert client.get('/api/people/weeks?scope=team',headers=worker_headers).status_code==200
    assert client.get('/api/people/weeks?scope=mine',headers=worker_headers).status_code==403


def weekly_work(client,headers,*,vehicle=False,assignees=None,scope=None,published=True):
    from tests.test_weekly_plans import create_cell,publish
    from tests.test_work_items_t34 import phase,create
    pid,units=setup_fleet(client,headers,2)
    with SessionLocal() as db:
        people={u.username:u.id for u in db.query(User)}
        p=db.get(Project,pid);p.members=[people['worker1'],people['worker2']];db.commit()
    task=create(client,headers,pid,phase(client,headers,pid),**({'kind':'vehicle','vehicle_step_key':'arrival_inspection'} if vehicle else {}))
    today=project_today('Asia/Shanghai');start=today-timedelta(days=today.weekday())
    row=create_cell(client,headers,pid,task,week_start=start.isoformat(),assignee_ids=assignees or [],scope=scope or {})
    if published:
        result=publish(client,headers,pid,row);assert result.status_code==200,result.text
        row=client.get(f'/api/projects/{pid}/weekly-plans',headers=headers,params={'week_start':start.isoformat(),'weeks':1}).json()['cells'][0]
    return pid,units,people,task,row


def test_real_weekly_claim_then_actual_fact_and_report_share_canonical_completion(client,pm_headers,worker_headers):
    pid,units,people,task,cell=weekly_work(client,pm_headers)
    response=client.get('/api/worker/week',headers=worker_headers);assert response.status_code==200,response.text
    view=response.json();assert not view['plans'] and [r['id'] for r in view['unassigned']]==[cell['id']]
    assert not view['unassigned'][0]['completion']['is_complete'] and view['unassigned'][0]['permissions']['claim']
    body=operation(pid,task['id'],kind='work',step_key='',weekly_cell_id=cell['id'])
    assert save(client,worker_headers,body).status_code==409  # reading and reporting never implicitly claim
    claimed=client.post(f"/api/projects/{pid}/weekly-plans/{cell['id']}/claim",headers=worker_headers,json={'version':cell['version']})
    assert claimed.status_code==200,claimed.text
    assert claimed.json()['assignee_ids']==[people['worker1']]
    assert client.post(f"/api/projects/{pid}/weekly-plans/{cell['id']}/claim",headers=worker_headers,json={'version':cell['version']}).status_code==409
    result=save(client,worker_headers,body);assert result.status_code==200,result.text
    view=client.get('/api/worker/week',headers=worker_headers).json()
    assert not view['unassigned'] and view['plans'][0]['completion']['completed_count']==1 and view['plans'][0]['completion']['is_complete']
    team=client.get('/api/people/weeks',headers=pm_headers).json()
    person=next(r for r in team['people'] if r['id']==people['worker1'])
    assert person['cells'][0]['completion']==view['plans'][0]['completion']
    with SessionLocal() as db:
        rows=db.query(FieldOperation).filter_by(project_id=pid).all()
        assert len(rows)==1 and rows[0].actor_id==people['worker1'] and rows[0].assisted_user_id is None


@pytest.mark.parametrize('change',['cancel','reassign','draft'])
def test_stale_field_cell_cannot_complete_cancelled_reassigned_or_unpublished_plan(client,pm_headers,worker_headers,change):
    pid,units,people,task,cell=weekly_work(client,pm_headers,published=change!='draft')
    if change!='draft':
        update={'version':cell['version'],'assignee_ids':[people['worker1']]}
        response=client.put(f"/api/projects/{pid}/weekly-plans/{cell['id']}",headers=pm_headers,json=update)
        assert response.status_code==200,response.text
        cell=response.json()
        update={'version':cell['version'],'is_cancelled':True,'reason':'负责人明确取消'} if change=='cancel' else {'version':cell['version'],'assignee_ids':[people['worker2']]}
        response=client.put(f"/api/projects/{pid}/weekly-plans/{cell['id']}",headers=pm_headers,json=update);assert response.status_code==200,response.text
    result=save(client,worker_headers,operation(pid,task['id'],kind='work',step_key='',weekly_cell_id=cell['id']))
    assert result.status_code==(403 if change=='reassign' else 404),result.text
    view=client.get('/api/worker/week',headers=worker_headers).json();assert not view['plans'] and not view['unassigned']
    with SessionLocal() as db:
        from app.models import Task
        assert not db.get(Task,task['id']).manually_completed and not db.query(FieldOperation).filter_by(project_id=pid).count()


@pytest.mark.parametrize('scope_kind',['batch','type'])
@pytest.mark.parametrize('kind',['vehicle','check'])
def test_plan_scope_applies_to_both_vehicle_and_exact_vehicle_check(client,pm_headers,worker_headers,scope_kind,kind):
    from app.models import VehicleUnit,Vehicle,CheckItem
    pid,units,people,task,cell=weekly_work(client,pm_headers,vehicle=True)
    with SessionLocal() as db:
        second=Vehicle(project_id=pid,vehicle_type='叉取式',model_name='另一车型',quantity=1);db.add(second);db.flush()
        db.get(VehicleUnit,units[1]).vehicle_id=second.id
        db.commit()
    scope={'vehicle_unit_ids':[units[0]]} if scope_kind=='batch' else {'vehicle_type':'潜伏式'}
    response=client.put(f"/api/projects/{pid}/weekly-plans/{cell['id']}",headers=pm_headers,json={'version':cell['version'],'scope':scope,'assignee_ids':[people['worker1']]})
    assert response.status_code==200,response.text
    targets=units
    if kind=='check':
        with SessionLocal() as db:
            from app.models import Task
            from app.services.vehicle_checks import snapshot_definitions,generate_for_units
            work=db.get(Task,task['id'])
            source=CheckItem(id=str(uuid.uuid4()),project_id=pid,task_id=task['id'],name='逐车真实核对',version=0,is_required=True,is_safety_critical=False)
            snapshot_definitions(db,work,[source]);generate_for_units(db,pid,[db.get(VehicleUnit,unit) for unit in units],work)
            db.commit();targets=[db.query(CheckItem).filter_by(task_id=task['id'],vehicle_unit_id=unit).one().id for unit in units]
    outside=save(client,worker_headers,operation(pid,targets[1],kind=kind,step_key='arrival_inspection' if kind=='vehicle' else '',weekly_cell_id=cell['id']))
    assert outside.status_code==404,outside.text
    inside=save(client,worker_headers,operation(pid,targets[0],kind=kind,step_key='arrival_inspection' if kind=='vehicle' else '',weekly_cell_id=cell['id']))
    assert inside.status_code==200,inside.text
    view=client.get('/api/worker/week',headers=worker_headers).json()
    assert all(view['plans'][0]['scope'][key]==value for key,value in scope.items()) and view['plans'][0]['work_item']['id']==task['id']
    with SessionLocal() as db:assert db.query(FieldOperation).filter_by(project_id=pid).count()==1


@pytest.mark.parametrize('actor',['pm','worker'])
@pytest.mark.parametrize('offset',[-40,1])
def test_original_matrix_entry_obeys_same_date_window_for_all_actors(client,pm_headers,worker_headers,actor,offset):
    from tests.test_vehicle_progress import write
    pid,unit,people=prepared(client,pm_headers)
    headers=pm_headers if actor=='pm' else worker_headers
    response=write(client,headers,pid,[unit],done_on=(project_today('Asia/Shanghai')+timedelta(days=offset)).isoformat())
    assert response.status_code==400,response.text
    with SessionLocal() as db:
        assert db.query(FieldOperation).filter_by(project_id=pid).count()==0 and db.query(VehicleProgress).filter_by(project_id=pid).count()==0
