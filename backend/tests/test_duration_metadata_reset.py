"""Cancel planning intent independently of protected physical execution data."""
import pytest

from app.db import SessionLocal
from app.models import DailyProgress, Task, TaskDurationOverride, ScheduleEntry, Project, ProjectSchedulePolicy, ChangeLog
from tests.test_manual_duration_regeneration import shortened_plan, resize  # noqa: F401


def request_body(client,headers,plan):
    policy=client.get(f'/api/projects/{plan[0]}/schedule/policy',headers=headers).json()['task_overrides'][0]
    return {'task_version':policy['task_version'],'override_version':policy['version']}


def endpoint(plan):return f'/api/projects/{plan[0]}/schedule/tasks/{plan[1]}/duration/auto'


def rows(db,model,pid):
    result=[{col.key:getattr(obj,col.key) for col in model.__table__.columns} for obj in db.query(model).filter_by(project_id=pid).all()]
    return sorted(result,key=lambda row:str(row.get('id',row.get('task_id',row.get('project_id')))))


def test_reported_unit_change_can_cancel_manual_budget_without_touching_work(client,admin_headers,shortened_plan):
    pid,tid,actor=shortened_plan
    with SessionLocal() as db:
        task=db.get(Task,tid);task.unit='个'
        rows=db.query(ScheduleEntry).filter_by(task_id=tid).all()
        rows[0].is_locked=True;rows[-1].is_confirmed=True
        linked_id=rows[0].id
        db.add(DailyProgress(project_id=pid,task_id=tid,schedule_entry_id=rows[0].id,user_id=actor,
                             work_date=rows[0].work_date,completed_quantity=1,client_uuid='reported-unit-rescue'))
        db.commit()
        task_version,override_version=task.version,db.get(TaskDurationOverride,tid).version
    path=f'/api/projects/{pid}/schedule/tasks/{tid}/duration/auto'
    before=client.get(f'/api/projects/{pid}/schedule',headers=admin_headers).json()
    body={'task_version':task_version,'override_version':override_version}
    preview=client.post(path+'/preview',headers=admin_headers,json=body)
    assert preview.status_code==200,preview.text
    body['preview_token']=preview.json()['preview_token']
    saved=client.put(path,headers=admin_headers,json=body)
    assert saved.status_code==200,saved.text
    assert saved.json()['task_version']==task_version+1 and saved.json()['override_version']==override_version+1
    assert client.get(f'/api/projects/{pid}/schedule',headers=admin_headers).json()==before
    with SessionLocal() as db:
        assert not db.get(TaskDurationOverride,tid).is_active
        assert db.get(TaskDurationOverride,tid).baseline_unit=='台'  # original evidence retained
        report=db.query(DailyProgress).filter_by(client_uuid='reported-unit-rescue').one()
        assert report.completed_quantity==1 and report.schedule_entry_id==linked_id
    generated=client.post(f'/api/projects/{pid}/schedule/generate',headers=admin_headers)
    assert generated.status_code==200,generated.text
    after=client.get(f'/api/projects/{pid}/schedule',headers=admin_headers).json()
    assert sum(row['planned_quantity'] for row in after)==10


def test_preview_cancel_is_read_only_for_policy_task_audit_and_execution(client,admin_headers,shortened_plan):
    pid,_,_=shortened_plan
    models=(Task,TaskDurationOverride,ScheduleEntry,DailyProgress,ChangeLog,ProjectSchedulePolicy)
    with SessionLocal() as db:before={m.__name__:rows(db,m,pid) for m in models}
    response=client.post(endpoint(shortened_plan)+'/preview',headers=admin_headers,json=request_body(client,admin_headers,shortened_plan))
    assert response.status_code==200,response.text
    assert '已有日程日期、数量' in response.json()['explanation']
    with SessionLocal() as db:assert {m.__name__:rows(db,m,pid) for m in models}==before


@pytest.mark.parametrize('change',['task_version','override_version','project_scale','new_report','entry_lock','target_change','unit_change'])
def test_metadata_confirm_rechecks_preview_facts_without_clearing_stale_intent(client,admin_headers,shortened_plan,change):
    pid,tid,actor=shortened_plan;path=endpoint(shortened_plan)
    body=request_body(client,admin_headers,shortened_plan)
    response=client.post(path+'/preview',headers=admin_headers,json=body)
    assert response.status_code==200,response.text
    body['preview_token']=response.json()['preview_token']
    with SessionLocal() as db:
        task=db.get(Task,tid);override=db.get(TaskDurationOverride,tid)
        if change=='task_version':task.version+=1
        if change=='override_version':override.version+=1
        if change=='project_scale':db.add(ProjectSchedulePolicy(project_id=pid,duration_scale=.5,version=1))
        if change=='new_report':db.add(DailyProgress(project_id=pid,task_id=tid,user_id=actor,work_date=db.get(Project,pid).start_date,
                                                    completed_quantity=0,client_uuid='report-after-preference-preview'))
        if change=='entry_lock':db.query(ScheduleEntry).filter_by(task_id=tid).first().is_locked=True
        if change=='target_change':task.target_quantity=11
        if change=='unit_change':task.unit='米'
        db.commit()
        before_work=rows(db,ScheduleEntry,pid);before_progress=rows(db,DailyProgress,pid)
    response=client.put(path,headers=admin_headers,json=body)
    assert response.status_code==409,response.text
    with SessionLocal() as db:
        assert db.get(TaskDurationOverride,tid).is_active
        assert rows(db,ScheduleEntry,pid)==before_work and rows(db,DailyProgress,pid)==before_progress


@pytest.mark.parametrize('status',['archived','completed','legacy_unknown'])
def test_metadata_reset_does_not_bypass_project_read_only_states(client,admin_headers,shortened_plan,status):
    pid,tid,_=shortened_plan
    body=request_body(client,admin_headers,shortened_plan)
    with SessionLocal() as db:db.get(Project,pid).status=status;db.commit()
    response=client.post(endpoint(shortened_plan)+'/preview',headers=admin_headers,json=body)
    assert response.status_code==400,response.text
    with SessionLocal() as db:assert db.get(TaskDurationOverride,tid).is_active


def test_metadata_reset_rejects_worker_and_invisible_pm(client,admin_headers,worker_headers,pm_headers,shortened_plan):
    body=request_body(client,admin_headers,shortened_plan);path=endpoint(shortened_plan)
    assert client.post(path+'/preview',headers=worker_headers,json=body).status_code==403
    assert client.post(path+'/preview',headers=pm_headers,json=body).status_code==404
    body['preview_token']='invalid'
    assert client.put(path,headers=worker_headers,json=body).status_code==403


def test_metadata_reset_rejects_replay_after_new_manual_confirmation(client,admin_headers,shortened_plan):
    pid,tid,_=shortened_plan;body=request_body(client,admin_headers,shortened_plan);path=endpoint(shortened_plan)
    preview=client.post(path+'/preview',headers=admin_headers,json=body);assert preview.status_code==200
    body['preview_token']=preview.json()['preview_token']
    assert client.put(path,headers=admin_headers,json=body).status_code==200
    resize(client,admin_headers,pid,tid,'2026-10-08','2026-10-09')
    replay=client.put(path,headers=admin_headers,json=body)
    assert replay.status_code==409
    with SessionLocal() as db:assert db.get(TaskDurationOverride,tid).is_active


def test_metadata_confirmation_requires_token_and_does_not_fake_execution(client,admin_headers,shortened_plan):
    pid,tid,_=shortened_plan;body=request_body(client,admin_headers,shortened_plan)
    response=client.put(endpoint(shortened_plan),headers=admin_headers,json=body)
    assert response.status_code==409
    with SessionLocal() as db:
        assert db.get(TaskDurationOverride,tid).is_active and db.query(DailyProgress).count()==0


def test_empty_schedule_budget_is_named_and_can_be_cancelled_after_unit_change(client,admin_headers,shortened_plan):
    pid,tid,_=shortened_plan
    with SessionLocal() as db:
        db.query(ScheduleEntry).filter_by(task_id=tid).delete()
        task=db.get(Task,tid);task.unit='米';task.version+=1
        db.get(Project,pid).status='draft';db.commit()
    policy=client.get(f'/api/projects/{pid}/schedule/policy',headers=admin_headers).json()['task_overrides'][0]
    assert policy['task_name']=='安装任务' and policy['task_version']>0
    path=endpoint(shortened_plan);body=request_body(client,admin_headers,shortened_plan)
    preview=client.post(path+'/preview',headers=admin_headers,json=body)
    assert preview.status_code==200 and preview.json()['remaining_quantity']==10
    body['preview_token']=preview.json()['preview_token']
    saved=client.put(path,headers=admin_headers,json=body)
    assert saved.status_code==200,saved.text
    with SessionLocal() as db:
        assert db.query(ScheduleEntry).count()==0 and db.query(DailyProgress).count()==0
        assert not db.get(TaskDurationOverride,tid).is_active
    assert client.post(f'/api/projects/{pid}/schedule/generate',headers=admin_headers).status_code==200
