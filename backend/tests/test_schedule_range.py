"""Task date adjustments are previewed, atomic and preserve field execution."""
from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Project, Phase, Module, Task, ScheduleEntry, User, DailyProgress


@pytest.fixture
def range_plan(client, admin_headers):
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username='admin').one()
        worker = db.query(User).filter_by(username='worker1').one()
        p = Project(name='工期调整', status='executing', start_date=date(2026, 10, 1),
                    end_date=date(2026, 11, 30), manager=admin.id, members=[worker.id],
                    rest_mode='two', skip_holidays=False)
        db.add(p); db.flush()
        phase = Phase(project_id=p.id, name='现场实施', sort_order=1)
        db.add(phase); db.flush()
        module = Module(project_id=p.id, phase_id=phase.id, name='安装')
        db.add(module); db.flush()
        task = Task(project_id=p.id, module_id=module.id, name='设备开箱', target_quantity=4, standard_hours=4)
        db.add(task); db.flush()
        entries = [ScheduleEntry(project_id=p.id, task_id=task.id, work_date=date(2026, 10, day),
                                 assignee_id=worker.id, planned_quantity=2, is_confirmed=True)
                   for day in (8, 9)]
        db.add_all(entries); db.commit()
        return p.id, task.id, worker.id


def body(client, headers, plan, start='2026-10-12', end='2026-10-14', mode='resize'):
    rows = client.get(f'/api/projects/{plan[0]}/schedule', headers=headers).json()
    return {'start_date': start, 'end_date': end, 'mode': mode,
            'entries': [{'id': e['id'], 'version': e['version']} for e in rows if e['task_id'] == plan[1] and e['status'] != 'skipped']}


def endpoint(plan, preview=False):
    return f'/api/projects/{plan[0]}/schedule/tasks/{plan[1]}/range' + ('/preview' if preview else '')


def test_preview_spreads_workdays_without_mutating_and_apply_preserves_ids_totals(client, admin_headers, range_plan):
    payload = body(client, admin_headers, range_plan)
    before = client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json()
    preview = client.post(endpoint(range_plan, True), headers=admin_headers, json=payload)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data['total_quantity'] == 4 and data['added'] == 1
    assert [day['work_date'] for day in data['distribution']] == ['2026-10-12', '2026-10-13', '2026-10-14']
    assert client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json() == before
    payload['preview_token'] = data['preview_token']
    applied = client.put(endpoint(range_plan), headers=admin_headers, json=payload)
    assert applied.status_code == 200, applied.text
    after = client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json()
    assert {e['id'] for e in before} <= {e['id'] for e in after}
    assert sum(e['planned_quantity'] for e in after) == pytest.approx(4)
    assert all(e['assignee_id'] == range_plan[2] and e['is_confirmed'] for e in after)


def test_range_preview_is_available_to_editors(client, admin_headers, range_plan):
    response = client.post(endpoint(range_plan, True), headers=admin_headers,
                           json=body(client, admin_headers, range_plan))
    assert response.status_code == 200, response.text


def test_generation_scale_changes_only_new_drafts_and_keeps_total(client, admin_headers, range_plan):
    with SessionLocal() as db:
        db.query(ScheduleEntry).filter_by(project_id=range_plan[0]).delete()
        task = db.get(Task, range_plan[1]); task.target_quantity = 10; task.standard_hours = 4
        db.commit()
    path = f'/api/projects/{range_plan[0]}/schedule'
    ordinary = client.get(path + '/preview', params={'duration_scale': 1}, headers=admin_headers).json()
    short = client.get(path + '/preview', params={'duration_scale': 0.5}, headers=admin_headers).json()
    assert short['after'] < ordinary['after']
    response = client.post(path + '/generate', headers=admin_headers, json={'duration_scale': 0.5})
    assert response.status_code == 200, response.text
    rows = client.get(path, headers=admin_headers).json()
    assert len(rows) == 3 and sum(row['planned_quantity'] for row in rows) == 10
    client.post(path + '/confirm', headers=admin_headers)
    kept = client.get(path, headers=admin_headers).json()
    client.post(path + '/generate', headers=admin_headers, json={'duration_scale': 0.25})
    assert client.get(path, headers=admin_headers).json() == kept


@pytest.mark.parametrize('start,end,mode', [('2026-09-30','2026-10-10','resize'), ('2026-11-25','2026-12-01','resize'), ('2026-10-15','2026-10-12','resize'), ('2026-10-10','2026-10-11','resize'), ('2026-10-12','2026-10-15','shift')])
def test_invalid_range_rejects_without_any_partial_update(client, admin_headers, range_plan, start, end, mode):
    payload = body(client, admin_headers, range_plan, start, end, mode)
    before = client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json()
    response = client.put(endpoint(range_plan), headers=admin_headers, json=payload)
    assert response.status_code == 400, response.text
    assert client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json() == before


@pytest.mark.parametrize('protection', ['lock','done','report','unlinked_zero_report','manual','zero_target','excess_total'])
def test_execution_quantity_protections_reject_the_whole_task(client, admin_headers, range_plan, protection):
    payload = body(client, admin_headers, range_plan)
    with SessionLocal() as db:
        task = db.get(Task, range_plan[1])
        row = db.get(ScheduleEntry, payload['entries'][-1]['id'])
        if protection == 'lock': row.is_locked = True
        if protection == 'done': row.status = 'done'
        if protection == 'manual': task.manually_completed = True
        if protection == 'zero_target': task.target_quantity = 0
        if protection == 'excess_total': task.target_quantity = 3
        if protection in ('report','unlinked_zero_report'):
            db.add(DailyProgress(project_id=range_plan[0],task_id=task.id, schedule_entry_id=row.id if protection == 'report' else None,
                                 user_id=range_plan[2], work_date=row.work_date, completed_quantity=1 if protection == 'report' else 0, client_uuid='range-protection'))
        db.commit()
    before = client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json()
    response = client.post(endpoint(range_plan, True), headers=admin_headers, json=payload)
    assert response.status_code == 400, response.text
    assert client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json() == before


@pytest.mark.parametrize('changed', ['version','added_row','goal','rest_rule','new_report'])
def test_save_revalidates_the_whole_preview(client, admin_headers, range_plan, changed):
    payload = body(client, admin_headers, range_plan)
    preview = client.post(endpoint(range_plan, True), headers=admin_headers, json=payload).json()
    payload['preview_token'] = preview['preview_token']
    with SessionLocal() as db:
        task = db.get(Task,range_plan[1]); row = db.get(ScheduleEntry,payload['entries'][-1]['id'])
        if changed == 'version': row.version = (row.version or 0) + 1
        if changed == 'added_row': db.add(ScheduleEntry(project_id=range_plan[0],task_id=task.id,work_date=date(2026,10,15),planned_quantity=0))
        if changed == 'goal': task.target_quantity = 0
        if changed == 'rest_rule': db.get(Project,range_plan[0]).rest_days = ['2026-10-13']
        if changed == 'new_report': db.add(DailyProgress(project_id=range_plan[0],task_id=task.id,schedule_entry_id=row.id,user_id=range_plan[2],work_date=row.work_date,completed_quantity=0,client_uuid='while-preview'))
        db.commit()
    before = client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json()
    response = client.put(endpoint(range_plan), headers=admin_headers, json=payload)
    assert response.status_code in (400,409), response.text
    assert client.get(f'/api/projects/{range_plan[0]}/schedule', headers=admin_headers).json() == before


def test_compression_keeps_old_ids_and_warns_about_capacity(client, admin_headers, range_plan):
    payload = body(client,admin_headers,range_plan,'2026-10-12','2026-10-12')
    response = client.post(endpoint(range_plan,True),headers=admin_headers,json=payload)
    assert response.status_code == 200, response.text
    preview=response.json()
    assert preview['added'] == 0 and preview['entries'] == 2
    assert preview['distribution'][0]['planned_quantity'] == 4
    assert any('16.0 小时' in warning for warning in preview['warnings'])
    payload['preview_token']=preview['preview_token']
    assert client.put(endpoint(range_plan),headers=admin_headers,json=payload).status_code == 200
    after=client.get(f'/api/projects/{range_plan[0]}/schedule',headers=admin_headers).json()
    assert {row['id'] for row in after} == {row['id'] for row in payload['entries']}
    assert all(row['work_date'] == '2026-10-12' for row in after)


def test_shift_rejects_rest_days_without_silently_compressing_then_moves_as_a_whole(client, admin_headers, range_plan):
    payload=body(client,admin_headers,range_plan,'2026-10-09','2026-10-10','shift')
    rejected=client.post(endpoint(range_plan,True),headers=admin_headers,json=payload)
    assert rejected.status_code==400 and '整体平移会落在休息日' in rejected.json()['detail']
    payload=body(client,admin_headers,range_plan,'2026-10-12','2026-10-13','shift')
    preview=client.post(endpoint(range_plan,True),headers=admin_headers,json=payload).json()
    assert preview['start_date']=='2026-10-12' and preview['end_date']=='2026-10-13'
    payload['preview_token']=preview['preview_token']
    assert client.put(endpoint(range_plan),headers=admin_headers,json=payload).status_code == 200
    after=client.get(f'/api/projects/{range_plan[0]}/schedule',headers=admin_headers).json()
    assert [row['planned_quantity'] for row in after] == [2,2]
    assert [row['work_date'] for row in after] == ['2026-10-12','2026-10-13']


def test_single_day_can_grow_without_erasing_old_or_cancelled_ids_or_advancing_state(client,admin_headers,range_plan):
    with SessionLocal() as db:
        rows=db.query(ScheduleEntry).filter_by(task_id=range_plan[1]).order_by(ScheduleEntry.id).all()
        rows[0].planned_quantity=4
        rows[1].status='skipped'; rows[1].is_locked=True; rows[1].work_date=date(2026,12,1)
        old_id,cancelled_id=rows[0].id,rows[1].id
        db.commit()
    payload=body(client,admin_headers,range_plan)
    preview=client.post(endpoint(range_plan,True),headers=admin_headers,json=payload).json()
    assert preview['entries']==3 and preview['added']==2 and preview['total_quantity']==4
    payload['preview_token']=preview['preview_token']
    assert client.put(endpoint(range_plan),headers=admin_headers,json=payload).status_code==200
    with SessionLocal() as db:
        assert db.get(ScheduleEntry,old_id) is not None
        assert db.get(ScheduleEntry,cancelled_id).work_date==date(2026,12,1)
        assert db.get(ScheduleEntry,cancelled_id).is_locked
        assert db.get(Project,range_plan[0]).status=='executing'


def test_holidays_and_manual_rest_are_previewed_without_silent_boundary_escape(client,admin_headers,range_plan):
    with SessionLocal() as db:
        p=db.get(Project,range_plan[0]); p.skip_holidays=True; p.rest_mode='none'; p.rest_days=['2026-10-08']
        db.commit()
    payload=body(client,admin_headers,range_plan,'2026-10-01','2026-10-09')
    preview=client.post(endpoint(range_plan,True),headers=admin_headers,json=payload)
    assert preview.status_code==200,preview.text
    assert [day['work_date'] for day in preview.json()['distribution']]==['2026-10-09']
    assert any('跳过 8 个休息日期' in warning for warning in preview.json()['warnings'])


def test_resize_matches_worker_two_decimal_precision_and_can_fully_finish(client,admin_headers,worker_headers,range_plan):
    with SessionLocal() as db:
        task=db.get(Task,range_plan[1]); task.target_quantity=1
        rows=db.query(ScheduleEntry).filter_by(task_id=task.id).all()
        rows[0].planned_quantity=1; db.delete(rows[1]); db.commit()
    payload=body(client,admin_headers,range_plan,'2026-10-01','2026-10-05')
    preview=client.post(endpoint(range_plan,True),headers=admin_headers,json=payload).json()
    assert [day['planned_quantity'] for day in preview['distribution']]==[.33,.33,.34]
    payload['preview_token']=preview['preview_token']
    assert client.put(endpoint(range_plan),headers=admin_headers,json=payload).status_code==200
    rows=client.get(f'/api/projects/{range_plan[0]}/schedule',headers=admin_headers).json()
    for row in rows:
        response=client.post('/api/worker/reports',headers=worker_headers,json={
            'project_id':range_plan[0],'task_id':range_plan[1],'schedule_entry_id':row['id'],
            'work_date':row['work_date'],'completed_quantity':row['planned_quantity'],'client_uuid':row['id'],
        })
        assert response.status_code==200,response.text
    after=client.get(f'/api/projects/{range_plan[0]}/schedule',headers=admin_headers).json()
    assert sum(row['completed_quantity'] for row in after)==pytest.approx(1)
    assert all(row['completed_quantity']==row['planned_quantity'] for row in after)


@pytest.mark.parametrize('quantity,expected_days,status',[(.01,0,400),(.02,2,200)])
def test_tiny_quantities_keep_positive_rows_and_real_endpoints(client,admin_headers,range_plan,quantity,expected_days,status):
    with SessionLocal() as db:
        task=db.get(Task,range_plan[1]); task.target_quantity=quantity
        rows=db.query(ScheduleEntry).filter_by(task_id=task.id).all()
        rows[0].planned_quantity=quantity; db.delete(rows[1]); db.commit()
    payload=body(client,admin_headers,range_plan)
    response=client.post(endpoint(range_plan,True),headers=admin_headers,json=payload)
    assert response.status_code==status,response.text
    if status==200:
        preview=response.json()
        assert len(preview['distribution'])==expected_days
        assert [row['work_date'] for row in preview['distribution']]==['2026-10-12','2026-10-14']
        assert all(row['planned_quantity']==.01 for row in preview['distribution'])
        assert preview['total_quantity']==quantity


@pytest.mark.parametrize('status',['draft','archived','completed','legacy_unknown'])
def test_publication_rejects_nonexecution_states_atomically(client,admin_headers,range_plan,status):
    with SessionLocal() as db:
        db.get(Project,range_plan[0]).status=status
        db.query(ScheduleEntry).filter_by(project_id=range_plan[0]).update({'is_confirmed':False})
        db.commit()
    path=f'/api/projects/{range_plan[0]}/schedule'
    before=client.get(path,headers=admin_headers).json()
    response=client.post(path+'/confirm',headers=admin_headers)
    assert response.status_code == 400,response.text
    single=client.put(f'/api/schedule/{before[0]["id"]}',headers=admin_headers,json={'is_confirmed':True,'version':before[0]['version']})
    assert single.status_code == 400,single.text
    assert client.get(path,headers=admin_headers).json() == before


def test_worker_cannot_adjust_and_other_pm_cannot_see_private_range(client,admin_headers,worker_headers,pm_headers,range_plan):
    payload=body(client,admin_headers,range_plan)
    assert client.post(endpoint(range_plan,True),headers=worker_headers,json=payload).status_code == 403
    assert client.put(endpoint(range_plan),headers=worker_headers,json=payload).status_code == 403
    assert client.post(endpoint(range_plan,True),headers=pm_headers,json=payload).status_code == 404
