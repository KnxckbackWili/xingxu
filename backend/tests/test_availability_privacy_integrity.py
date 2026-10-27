"""当前人员周计划的可见范围、不可用隐私及原个人事项保全。"""


from datetime import date,timedelta
from fastapi import HTTPException
from app.db import SessionLocal
from app.models import Project,User,WeeklyPlanCell


def test_private_events_defer_only_their_project_and_remain_owner_manageable(client, pm_headers, admin_headers):
    from datetime import timedelta
    from app.db import SessionLocal
    from app.models import Project, ProjectArchive, PersonalEvent
    from app.services.report_scheduler import purge_soft_deleted_projects
    from app.time_utils import utcnow
    ids = [client.post('/api/projects', headers=pm_headers, json={
        'name': name, 'start_date': '2026-01-01', 'end_date': '2026-12-31', 'new_vehicles': False}).json()['id']
        for name in ['Private calendar retention', 'Ordinary retention']]
    with SessionLocal() as db:
        from app.models import User
        owner=db.query(User).filter_by(username='pm').one()
        event=PersonalEvent(project_id=ids[0],user_id=owner.id,work_date=date(2026,1,1),title='OWNER ONLY NOTE',notes='PRIVATE EVENT DETAILS')
        db.add(event);db.commit();event={'id':event.id}
    with SessionLocal() as db:
        for pid in ids: db.get(Project, pid).deleted_at = utcnow()-timedelta(days=31)
        db.commit()
        result = purge_soft_deleted_projects(db); db.commit()
        assert result['purged'] == result['blocked'] == 0 and result['disabled']
        assert 'OWNER ONLY' not in str(result) and 'PRIVATE EVENT' not in str(result)
        assert db.get(Project, ids[0]) is not None and db.get(Project, ids[1]) is not None
        assert db.query(ProjectArchive).filter_by(project_id=ids[0]).count() == 0
    events = client.get('/api/dashboard/personal-events', headers=pm_headers).json()
    assert any(item['id'] == event['id'] for item in events)
    assert client.delete(f"/api/dashboard/personal-events/{event['id']}", headers=admin_headers).status_code == 410
    assert client.delete(f"/api/dashboard/personal-events/{event['id']}", headers=pm_headers).status_code == 410
    with SessionLocal() as db:
        assert purge_soft_deleted_projects(db)['purged'] == 0
        db.commit()
        assert db.get(Project, ids[0]) is not None


def _ids():
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        return {u.username: u.id for u in db.query(User).all()}


def _leave(client, headers, uid, *, start=None, end=None):
    today = date.today().isoformat()
    response = client.post(f"/api/users/{uid}/unavailability", headers=headers, json={
        "start_date": start or today, "end_date": end or today,
        "reason": "私人病假", "note": "私人医疗说明不可向同事公开",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_interval_partial_updates_revalidate_against_fresh_locked_row(client, pm_headers):
    from app.db import SessionLocal
    from app.models import User, UserUnavailability
    from app.routers.availability import update_unavailability, UnavailabilityUpdate
    ids = _ids()
    uid = ids["worker1"]
    rid = _leave(client, pm_headers, uid, start="2026-10-01", end="2026-10-10")
    # Both requests have already read [1, 10]. Their independent edits are each
    # locally valid, but combining them without a locked reread creates [8, 3].
    with SessionLocal() as first, SessionLocal() as second:
        old_first = first.get(UserUnavailability, rid)
        old_second = second.get(UserUnavailability, rid)
        assert old_first.start_date == old_second.start_date == date(2026, 10, 1)
        update_unavailability(uid, rid, UnavailabilityUpdate(start_date=date(2026, 10, 8)),
                              first.get(User, ids["pm"]), first)
        try:
            update_unavailability(uid, rid, UnavailabilityUpdate(end_date=date(2026, 10, 3)),
                                  second.get(User, ids["pm"]), second)
        except HTTPException as exc:
            assert exc.status_code in (400, 409)
            second.rollback()
    with SessionLocal() as check:
        saved = check.get(UserUnavailability, rid)
        assert saved.start_date <= saved.end_date, "Two accepted partial updates created an impossible interval"
        assert saved.start_date == date(2026, 10, 8)
        assert saved.end_date == date(2026, 10, 10)


def _work(db,ids,*,name='人员周项目',day=None,deleted=False,cancelled=False,published=True,assignee=None,manager=None):
    from app.models import ProjectMember,Phase,Task
    from app.time_utils import project_today,utcnow
    day=day or project_today('Asia/Shanghai');day-=timedelta(days=day.weekday())
    manager=manager or ids['pm']
    p=Project(name=name,start_date=day,end_date=day+timedelta(days=30),manager=manager,members=[ids['worker1'],ids['worker2']],
        status='executing',deleted_at=utcnow() if deleted else None)
    db.add(p);db.flush()
    for uid in [manager,ids['worker1'],ids['worker2']]:db.add(ProjectMember(project_id=p.id,user_id=uid))
    phase=Phase(project_id=p.id,name='现场工作');db.add(phase);db.flush()
    task=Task(project_id=p.id,phase_id=phase.id,name='现场核对',quantity_type='fixed',target_quantity=None)
    db.add(task);db.flush()
    db.add(WeeklyPlanCell(project_id=p.id,task_id=task.id,scope_key='all',scope={},week_start=day,mode='in_progress',
        assignee_ids=[assignee or ids['worker1']],published=published,is_cancelled=cancelled))
    db.commit();return p.id


def test_people_week_does_not_bypass_peer_unavailability_privacy(client,pm_headers,worker_headers):
    ids=_ids()
    with SessionLocal() as db:
        _work(db,ids);_work(db,ids,assignee=ids['worker2']);db.get(User,ids['worker1']).permission_overrides={'workspace.view':True};db.commit()
    _leave(client,pm_headers,ids['worker2'])
    assert client.get(f"/api/users/{ids['worker2']}/unavailability",headers=worker_headers).status_code==403
    response=client.get('/api/people/weeks',headers=worker_headers);assert response.status_code==200,response.text
    assert '私人医疗说明' not in response.text and '私人病假' not in response.text
    peer=next(r for r in response.json()['people'] if r['id']==ids['worker2'])
    assert len(peer['unavailable'])==1 and 'reason' not in peer['unavailable'][0] and 'note' not in peer['unavailable'][0]


def test_people_week_conflicts_include_later_week_and_only_visible_published_projects(client,pm_headers):
    from app.time_utils import project_today
    ids=_ids();start=project_today('Asia/Shanghai');start-=timedelta(days=start.weekday());later=start+timedelta(weeks=2)
    with SessionLocal() as db:
        left=_work(db,ids,name='我的未来安排甲',day=later);right=_work(db,ids,name='我的未来安排乙',day=later)
        _work(db,ids,name='不可见项目原文',day=later,manager=ids['admin'])
        _work(db,ids,name='已删除原安排',day=later,deleted=True)
        _work(db,ids,name='已取消原安排',day=later,cancelled=True)
        _work(db,ids,name='未发布原安排',day=later,published=False)
    response=client.get('/api/people/weeks',headers=pm_headers,params={'week_start':start.isoformat(),'weeks':4})
    assert response.status_code==200,response.text
    for hidden in ('不可见项目原文','已删除原安排'):assert hidden not in response.text
    row=next(r for r in response.json()['people'] if r['id']==ids['worker1'])
    assert {c['project_id'] for c in row['cells']}=={left,right}
    assert row['conflicts']==[{'week_start':later.isoformat(),'project_ids':sorted([left,right])}]


def test_people_week_excludes_inactive_members_for_every_viewer(client,pm_headers,admin_headers):
    ids=_ids()
    with SessionLocal() as db:_work(db,ids);db.get(User,ids['worker2']).is_active=False;db.commit()
    for headers in (pm_headers,admin_headers):
        response=client.get('/api/people/weeks',headers=headers);assert response.status_code==200,response.text
        assert ids['worker2'] not in {r['id'] for r in response.json()['people']}


def test_overlapping_unavailability_preserves_remaining_interval_after_cancel(client,pm_headers):
    ids=_ids()
    with SessionLocal() as db:_work(db,ids)
    first=_leave(client,pm_headers,ids['worker1']);second=_leave(client,pm_headers,ids['worker1'])
    def periods():
        response=client.get('/api/people/weeks',headers=pm_headers);assert response.status_code==200,response.text
        return next(r for r in response.json()['people'] if r['id']==ids['worker1'])['unavailable']
    assert len(periods())==2
    assert client.delete(f"/api/users/{ids['worker1']}/unavailability/{first}",headers=pm_headers).status_code==200
    assert len(periods())==1
    assert client.delete(f"/api/users/{ids['worker1']}/unavailability/{second}",headers=pm_headers).status_code==200
    assert periods()==[]
