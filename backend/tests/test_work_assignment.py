"""维修周安排保留同一真实问题，改派不会冒充实际处理人。"""
from datetime import timedelta
import pytest
from app.db import SessionLocal
from app.models import Project,User,Task,WeeklyPlanCell,VehicleLifecycleEvent,FieldOperation
from app.time_utils import project_today


def setup_work(client,headers):
    from tests.test_vehicle_progress import setup_fleet
    pid,units=setup_fleet(client,headers,1)
    with SessionLocal() as db:
        p=db.get(Project,pid);p.members=[u.id for u in db.query(User).filter(User.username.in_(['worker1','worker2']))];db.commit()
    unit=units[0]
    response=client.post(f'/api/projects/{pid}/vehicle-units/{unit}/events',headers=headers,
        json={'event_type':'fault','event_date':'2026-09-16','title':'驱动轮故障','handler':'原实际处理人','is_closed':False,'status_after':'fault'})
    assert response.status_code==200,response.text
    return pid,unit,response.json()['id']


def repair(client,headers,pid,unit,event,assignees):
    today=project_today('Asia/Shanghai');start=today-timedelta(days=today.weekday())
    return client.post(f'/api/projects/{pid}/vehicle-units/{unit}/events/{event}/weekly-plans',headers=headers,
        json={'week_start':start.isoformat(),'assignee_ids':assignees,'mode':'finish','notes':'携带驱动轮'})


def test_repair_shared_work_survives_weekly_publication_and_reassignment(client,pm_headers,worker_headers):
    from tests.test_weekly_plans import publish
    pid,unit,event=setup_work(client,pm_headers)
    with SessionLocal() as db:ids={u.username:u.id for u in db.query(User)}
    response=repair(client,pm_headers,pid,unit,event,[ids['worker1']]);assert response.status_code==200,response.text
    first=response.json();cell=first['cell'];assert first['created'] and not cell['published']
    assert publish(client,pm_headers,pid,cell).status_code==200
    url=f"/api/projects/{pid}/weekly-plans/{cell['id']}"
    changed=client.put(url,headers=pm_headers,json={'version':1,'assignee_ids':[ids['worker2']]})
    assert changed.status_code==200 and changed.json()['assignee_ids']==[ids['worker2']]
    assert client.put(url,headers=pm_headers,json={'version':1,'assignee_ids':[ids['worker1']]}).status_code==409
    next_week=(project_today('Asia/Shanghai')+timedelta(weeks=1));next_week-=timedelta(days=next_week.weekday())
    another=client.post(f'/api/projects/{pid}/vehicle-units/{unit}/events/{event}/weekly-plans',headers=pm_headers,
        json={'week_start':next_week.isoformat(),'assignee_ids':[ids['worker2']],'mode':'in_progress'})
    assert another.status_code==200 and not another.json()['created'] and another.json()['task_id']==first['task_id']
    with SessionLocal() as db:
        assert db.get(Task,first['task_id']).source_vehicle_event_id==event
        assert db.query(Task).filter_by(project_id=pid,source_vehicle_event_id=event).count()==1
        assert db.query(WeeklyPlanCell).filter_by(task_id=first['task_id']).count()==2
        original=db.get(VehicleLifecycleEvent,event);assert original.handler=='原实际处理人' and not original.is_closed
        assert not db.query(FieldOperation).filter_by(project_id=pid).count()


def test_repair_rejects_wrong_person_scope_and_closed_fault(client,pm_headers,worker_headers):
    pid,unit,event=setup_work(client,pm_headers)
    with SessionLocal() as db:wid=db.query(User).filter_by(username='worker1').one().id
    assert repair(client,worker_headers,pid,unit,event,[wid]).status_code==403
    assert repair(client,pm_headers,pid,unit,event,['missing']).status_code==400
    assert repair(client,pm_headers,pid,'missing',event,[wid]).status_code==404
    closed=client.put(f'/api/projects/{pid}/vehicle-units/{unit}/events/{event}',headers=pm_headers,
        json={'is_closed':True,'verification':'试运行正常','status_after':'normal'})
    assert closed.status_code==200,closed.text
    assert repair(client,pm_headers,pid,unit,event,[wid]).status_code==400


@pytest.mark.parametrize('status',['suspended','completed','archived'])
def test_repair_weekly_plan_rejects_terminal_or_paused_project_without_writes(client,pm_headers,status):
    pid,unit,event=setup_work(client,pm_headers)
    with SessionLocal() as db:p=db.get(Project,pid);p.status=status;db.commit()
    response=repair(client,pm_headers,pid,unit,event,[]);assert response.status_code==400,response.text
    with SessionLocal() as db:
        assert not db.query(WeeklyPlanCell).filter_by(project_id=pid).count()
        assert not db.query(Task).filter_by(project_id=pid,source_vehicle_event_id=event).count()
