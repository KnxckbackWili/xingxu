"""旧按日写入口不改变原行；周计划设置有明确版本边界。"""
from datetime import date
import pytest
from app.db import SessionLocal
from app.models import ScheduleEntry,DailyProgress,Task,Project
from tests.test_project_lifecycle_boundaries import project,task_entry
from tests.test_weekly_plans import setup


def test_retired_daily_mutations_leave_all_original_rows_unchanged(client,pm_headers):
    pid=project(client,pm_headers);tid,eid,_=task_entry(pid,confirmed=True,locked=True)
    with SessionLocal() as db:
        db.add(DailyProgress(project_id=pid,task_id=tid,schedule_entry_id=eid,user_id=db.get(Project,pid).manager,
            work_date=date(2026,9,1),completed_quantity=.1,client_uuid='preserved-before-retired-routes'));db.commit()
        from app.services.project_retention import _row
        before={model.__tablename__:[_row(row) for row in db.query(model).filter_by(project_id=pid)] for model in (ScheduleEntry,DailyProgress,Task)}
    for method,path,body in [('post',f'/api/projects/{pid}/schedule/generate',{}),('post',f'/api/projects/{pid}/schedule/reschedule',{}),
        ('post',f'/api/projects/{pid}/schedule/confirm',{}),('post',f'/api/projects/{pid}/schedule/apply-suggestions',{'suggestions':[]}),
        ('put',f'/api/schedule/{eid}',{'work_date':'2026-11-01','planned_quantity':99}),('delete',f'/api/schedule/{eid}',{})]:
        response=client.request(method,path,headers=pm_headers,json=body);assert response.status_code==410,response.text
    with SessionLocal() as db:
        assert {model.__tablename__:[_row(row) for row in db.query(model).filter_by(project_id=pid)] for model in (ScheduleEntry,DailyProgress,Task)}==before
    source=client.get(f'/api/projects/{pid}/weekly-plans/legacy-source',headers=pm_headers)
    assert source.status_code==200 and source.json()['read_only']
    assert source.json()['entries']==before['schedule_entries']


@pytest.mark.parametrize('changes',[{'rest_mode':'pattern'},{'rest_days':['not-a-date']},{'skip_holidays':'not-a-bool'}])
def test_current_week_settings_reject_invalid_calendar_without_writing(client,pm_headers,changes):
    pid,_,_,_=setup(client,pm_headers)
    path=f'/api/projects/{pid}/weekly-plans/settings';before=client.get(path,headers=pm_headers).json()
    body={'version':before['version'],'rest_mode':'none','rest_days':[],'skip_holidays':False,**changes}
    response=client.put(path,headers=pm_headers,json=body);assert response.status_code==422,response.text
    assert client.get(path,headers=pm_headers).json()==before
