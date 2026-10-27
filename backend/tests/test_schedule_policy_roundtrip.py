"""旧倍率、人工工期与审计完整便携保全，不重启按日规划。"""
from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Project,Task,ScheduleEntry,DailyProgress,ProjectSchedulePolicy,TaskDurationOverride,ChangeLog,FieldOperation,WeeklyPlanCell
from tests.test_project_lifecycle_boundaries import project,task_entry


def source_project(client,headers,*,active=True):
    pid=project(client,headers,'旧策略只读来源');tid,eid,_=task_entry(pid,confirmed=True,locked=True)
    with SessionLocal() as db:
        actor=db.get(Project,pid).manager
        db.add(ProjectSchedulePolicy(project_id=pid,duration_scale=.5,version=7,updated_by=actor))
        db.add(TaskDurationOverride(task_id=tid,project_id=pid,workdays=2,baseline_quantity=10,baseline_unit='台',is_active=active,version=8,updated_by=actor,recovered_from_log_id='original-resize-log'))
        db.add(DailyProgress(project_id=pid,task_id=tid,schedule_entry_id=eid,user_id=actor,work_date=date(2026,9,1),completed_quantity=.3,client_uuid='original-policy-report'))
        db.commit()
    return pid,tid


def exported(client,headers,pid):
    response=client.get(f'/api/projects/{pid}/export/json',headers=headers);assert response.status_code==200,response.text
    return response.json()


def copy_project(client,headers,pid,entrypoint,payload=None):
    response=client.post('/api/projects/import/json',headers=headers,json=payload or exported(client,headers,pid)) if entrypoint=='import' else client.post(f'/api/projects/{pid}/clone',headers=headers,json={'name':'只读来源副本'})
    assert response.status_code==200,response.text
    return response.json()['id']


@pytest.mark.parametrize('entrypoint',['import','clone'])
@pytest.mark.parametrize('active',[True,False])
def test_portable_history_keeps_policy_and_tombstone_without_active_execution(client,pm_headers,entrypoint,active):
    pid,tid=source_project(client,pm_headers,active=active)
    payload=exported(client,pm_headers,pid);source=payload['legacy_planning_source']
    assert source['read_only'] and payload['planning_schedule']['read_only']
    assert source['project_schedule_policies'][0]['duration_scale']==.5 and source['project_schedule_policies'][0]['version']==7
    assert source['task_duration_overrides'][0]['task_id']==tid and source['task_duration_overrides'][0]['is_active']==active
    new=copy_project(client,pm_headers,pid,entrypoint,payload)
    with SessionLocal() as db:
        current=db.get(Project,new);assert current.status=='preparing'
        assert current.portable_unverified_snapshot['legacy_planning_source']==source
        for model in (ProjectSchedulePolicy,TaskDurationOverride,DailyProgress,ScheduleEntry,FieldOperation,WeeklyPlanCell):assert db.query(model).filter_by(project_id=new).count()==0
        assert all(not row.manually_completed for row in db.query(Task).filter_by(project_id=new))
        assert db.get(TaskDurationOverride,tid).version==8


@pytest.mark.parametrize('entrypoint',['import','clone'])
def test_duplicate_work_names_preserve_original_policy_identity_only_in_source(client,pm_headers,entrypoint):
    pid,tid=source_project(client,pm_headers)
    with SessionLocal() as db:
        original=db.get(Task,tid)
        second=Task(project_id=pid,module_id=original.module_id,phase_id=original.phase_id,name=original.name,quantity_type='manual',target_quantity=20,unit='台')
        db.add(second);db.flush();sid=second.id
        db.add(TaskDurationOverride(task_id=sid,project_id=pid,workdays=3,baseline_quantity=20,baseline_unit='台',is_active=True));db.commit()
    new=copy_project(client,pm_headers,pid,entrypoint)
    with SessionLocal() as db:
        rows=db.get(Project,new).portable_unverified_snapshot['legacy_planning_source']['task_duration_overrides']
        assert {row['task_id']:row['workdays'] for row in rows}=={tid:2,sid:3}
        assert db.query(TaskDurationOverride).filter_by(project_id=new).count()==0
        copied=db.query(Task).filter_by(project_id=new).all();assert len(copied)==2 and len({r.name for r in copied})==1


def test_export_keeps_adjustment_audit_without_reconstructing_missing_budget(client,pm_headers):
    pid,tid=source_project(client,pm_headers)
    with SessionLocal() as db:
        db.delete(db.get(TaskDurationOverride,tid));db.add(ChangeLog(project_id=pid,entity_type='task',entity_id=tid,action='schedule_range',detail='原工期修改审计完整原文',old_value={'days':9},new_value={'days':2}));db.commit()
        before=db.query(ChangeLog).filter_by(project_id=pid,entity_type='task',action='schedule_range').count()
    source=exported(client,pm_headers,pid)['legacy_planning_source']
    assert source['task_duration_overrides']==[] and source['schedule_range_audits'][0]['detail']=='原工期修改审计完整原文'
    assert source['schedule_range_audits'][0]['old_value']=={'days':9}
    with SessionLocal() as db:
        assert db.get(TaskDurationOverride,tid) is None and db.query(ChangeLog).filter_by(project_id=pid,entity_type='task',action='schedule_range').count()==before


def test_old_portable_intent_is_quarantined_without_reinterpreting_retired_budget_rules(client,pm_headers):
    pid,_=source_project(client,pm_headers);payload=exported(client,pm_headers,pid)
    old={'duration_scale':-3,'task_durations':[{'task_source_id':'unproven-source','workdays':3,'baseline_quantity':.01,'unknown_original_field':'保全原值'}]}
    payload['planning_schedule']=old;new=copy_project(client,pm_headers,pid,'import',payload)
    with SessionLocal() as db:
        assert db.get(Project,new).portable_unverified_snapshot['legacy_planning_schedule']==old
        assert db.query(TaskDurationOverride).filter_by(project_id=new).count()==db.query(ScheduleEntry).filter_by(project_id=new).count()==0
    payload['planning_schedule']=[]
    with SessionLocal() as db:before=db.query(Project).count()
    response=client.post('/api/projects/import/json',headers=pm_headers,json=payload);assert response.status_code==400,response.text
    with SessionLocal() as db:assert db.query(Project).count()==before


def test_worker_cannot_import_or_clone_source_history(client,pm_headers,worker_headers):
    pid,_=source_project(client,pm_headers)
    assert client.post('/api/projects/import/json',headers=worker_headers,json=exported(client,pm_headers,pid)).status_code==403
    assert client.post(f'/api/projects/{pid}/clone',headers=worker_headers,json={}).status_code==403


def test_clone_reference_copy_stays_independent_of_retired_policy_metadata(client,pm_headers):
    from app.config import UPLOAD_DIR
    pid,tid=source_project(client,pm_headers);stored='policy-source-reference.txt';content=b'Original policy reference text\n'
    UPLOAD_DIR.mkdir(parents=True,exist_ok=True);(UPLOAD_DIR/stored).write_bytes(content)
    with SessionLocal() as db:db.get(Task,tid).reference_docs=[{'stored_name':stored,'filename':'original-reference.txt','size':len(content)}];db.commit()
    new=copy_project(client,pm_headers,pid,'clone')
    with SessionLocal() as db:
        task=db.query(Task).filter_by(project_id=new).one();copied=task.reference_docs[0]['stored_name']
        assert copied!=stored and db.get(Task,tid).reference_docs[0]['stored_name']==stored and db.query(TaskDurationOverride).filter_by(project_id=new).count()==0
    assert (UPLOAD_DIR/copied).read_bytes()==(UPLOAD_DIR/stored).read_bytes()==content
    (UPLOAD_DIR/copied).write_bytes(b'Independent clone changed\n');assert (UPLOAD_DIR/stored).read_bytes()==content
