"""本人的周计划和实际记录不绕过项目终态或当地日期。"""
from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Project,Task,WeeklyPlanCell,FieldOperation
from tests.test_project_lifecycle_boundaries import project
from tests.test_weekly_plans import setup,create_cell,publish


def test_report_defaults_to_project_local_calendar_date(client, pm_headers, monkeypatch):
    pid = project(client, pm_headers)
    monkeypatch.setattr('app.time_utils.project_today', lambda tz: date(2026, 9, 2))
    result = client.get(f'/api/projects/{pid}/report', headers=pm_headers)
    assert result.status_code == 200, result.text
    assert result.json()['period_label'] == '2026-08-31 ~ 2026-09-06'
    assert result.json()['generated_at'] == '2026-09-02'


@pytest.mark.parametrize('status',['completed','archived'])
@pytest.mark.parametrize('operation',['plan_create','plan_edit','field_write'])
def test_terminal_project_cannot_be_changed_through_week_or_actual_entry(client,pm_headers,status,operation):
    from tests.test_field_week_t33 import operation as actual
    pid,units,_,task=setup(client,pm_headers)
    row=create_cell(client,pm_headers,pid,task)
    with SessionLocal() as db:db.get(Project,pid).status=status;db.commit()
    if operation=='plan_create':response=client.post(f'/api/projects/{pid}/weekly-plans',headers=pm_headers,json={'task_id':task['id'],'week_start':'2026-12-07'})
    elif operation=='plan_edit':response=client.put(f"/api/projects/{pid}/weekly-plans/{row['id']}",headers=pm_headers,json={'version':row['version'],'notes':'终态不能改'})
    else:response=client.post('/api/worker/operations',headers=pm_headers,json=actual(pid,units[0]))
    assert response.status_code==400,response.text
    with SessionLocal() as db:
        assert not db.get(Task,task['id']).manually_completed and db.query(WeeklyPlanCell).filter_by(project_id=pid).count()==1
        assert not db.query(FieldOperation).filter_by(project_id=pid).count()
        assert db.get(WeeklyPlanCell,row['id']).notes==''


def test_weekly_clear_assignees_requires_fresh_version_and_keeps_actuals(client,pm_headers):
    from app.models import User
    pid,_,_,task=setup(client,pm_headers)
    with SessionLocal() as db:uid=db.get(Project,pid).manager
    cell=create_cell(client,pm_headers,pid,task,assignee_ids=[uid]);assert publish(client,pm_headers,pid,cell).status_code==200
    url=f"/api/projects/{pid}/weekly-plans/{cell['id']}"
    response=client.put(url,headers=pm_headers,json={'version':1,'assignee_ids':[]})
    assert response.status_code==200 and response.json()['assignee_ids']==[]
    assert client.put(url,headers=pm_headers,json={'version':1,'assignee_ids':[uid]}).status_code==409
    with SessionLocal() as db:
        assert not db.get(Task,task['id']).manually_completed and not db.query(FieldOperation).filter_by(project_id=pid).count()
