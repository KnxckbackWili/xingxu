"""An explicitly saved task duration survives a subsequent scheduling call."""
from datetime import date

import pytest

from app.db import SessionLocal
from app.models import Module, Phase, Project, Task, User, ChangeLog, TaskDurationOverride, ScheduleEntry


def resize(client, headers, pid, tid, start, end, mode="resize"):
    schedule = f"/api/projects/{pid}/schedule"
    rows = client.get(schedule, headers=headers).json()
    body = {"start_date": start, "end_date": end, "mode": mode,
            "entries": [{"id": row["id"], "version": row["version"]} for row in rows
                        if row["task_id"] == tid and row["status"] != "skipped"]}
    path = schedule + f"/tasks/{tid}/range"
    preview = client.post(path + "/preview", headers=headers, json=body)
    assert preview.status_code == 200, preview.text
    body["preview_token"] = preview.json()["preview_token"]
    saved = client.put(path, headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    return preview.json(), saved.json()


@pytest.fixture
def shortened_plan(client, admin_headers):
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").one()
        worker = db.query(User).filter_by(username="worker1").one()
        project = Project(name="人工缩短后重排", status="executing", manager=admin.id,
                          members=[worker.id], start_date=date(2026, 10, 8),
                          end_date=date(2026, 11, 30), rest_mode="two", skip_holidays=False)
        db.add(project); db.flush()
        phase = Phase(project_id=project.id, name="现场实施", sort_order=1)
        db.add(phase); db.flush()
        module = Module(project_id=project.id, phase_id=phase.id, name="安装")
        db.add(module); db.flush()
        task = Task(project_id=project.id, module_id=module.id, name="安装任务",
                    target_quantity=10, standard_hours=4)
        db.add(task); db.commit()
        pid, tid, actor = project.id, task.id, admin.id

    schedule = f"/api/projects/{pid}/schedule"
    response = client.post(schedule + "/generate", headers=admin_headers)
    assert response.status_code == 200, response.text
    rows = client.get(schedule, headers=admin_headers).json()
    assert len({row["work_date"] for row in rows}) == 5
    payload = {"start_date": "2026-10-08", "end_date": "2026-10-09", "mode": "resize",
               "entries": [{"id": row["id"], "version": row["version"]} for row in rows]}
    path = schedule + f"/tasks/{tid}/range"
    preview = client.post(path + "/preview", headers=admin_headers, json=payload)
    assert preview.status_code == 200, preview.text
    payload["preview_token"] = preview.json()["preview_token"]
    response = client.put(path, headers=admin_headers, json=payload)
    assert response.status_code == 200, response.text
    saved = client.get(schedule, headers=admin_headers).json()
    assert sorted({row["work_date"] for row in saved}) == ["2026-10-08", "2026-10-09"]
    assert sum(row["planned_quantity"] for row in saved) == pytest.approx(10)
    assert all(not row["is_locked"] and not row["is_confirmed"] for row in saved)
    return pid, tid, actor


@pytest.mark.parametrize("flow", ["generate", "overdue"])
def test_saved_shorter_duration_survives_preview_and_rescheduling(client, admin_headers, shortened_plan, flow):
    """Five estimated days → explicitly save two days → later calls keep two days."""
    pid, tid, actor = shortened_plan
    schedule = f"/api/projects/{pid}/schedule"
    before = client.get(schedule, headers=admin_headers).json()
    if flow == "generate":
        preview = client.get(schedule + "/preview", headers=admin_headers)
        response = client.post(schedule + "/generate", headers=admin_headers)
        expected_dates = ["2026-10-08", "2026-10-09"]
    else:
        params = {"start_date": "2026-10-12"}
        preview = client.get(schedule + "/reschedule-preview", headers=admin_headers, params=params)
        response = client.post(schedule + "/reschedule", headers=admin_headers, json=params)
        expected_dates = ["2026-10-12", "2026-10-13"]
    assert preview.status_code == 200, preview.text
    assert response.status_code == 200, response.text
    after = client.get(schedule, headers=admin_headers).json()
    dates = sorted({row["work_date"] for row in after})
    assert sum(row["planned_quantity"] for row in after) == pytest.approx(10)
    assert all(not row["is_locked"] and not row["is_confirmed"] for row in after)
    assert (preview.json()["after"], dates) == (2, expected_dates), (
        "人工确认的2工作日被重新估算覆盖："
        f"preview_after={preview.json()['after']}, saved_dates={sorted({r['work_date'] for r in before})}, "
        f"rescheduled_dates={dates}"
    )


def test_saved_duration_scales_with_changed_quantity_and_is_not_scaled_twice(client, admin_headers, shortened_plan):
    pid, tid, _ = shortened_plan
    with SessionLocal() as db:
        task = db.get(Task, tid); task.target_quantity = 20; db.commit()
    schedule = f"/api/projects/{pid}/schedule"
    r = client.post(schedule + "/generate", headers=admin_headers, json={"duration_scale": .5})
    assert r.status_code == 200, r.text
    rows = client.get(schedule, headers=admin_headers).json()
    assert len({r['work_date'] for r in rows}) == 4  # 2 days × 20 / baseline 10; no extra .5.
    assert sum(r['planned_quantity'] for r in rows) == pytest.approx(20)
    estimate = r.json()['tasks'][0]
    assert estimate['duration_source'] == 'manual_range'
    assert estimate['manual_workdays'] == 2 and estimate['manual_baseline_quantity'] == 10


def test_restoring_automatic_requires_preview_and_confirmation(client, admin_headers, shortened_plan):
    pid, tid, _ = shortened_plan
    schedule = f"/api/projects/{pid}/schedule"
    before = client.get(schedule, headers=admin_headers).json()
    body = {'start_date': '2026-10-08', 'end_date': '2026-10-09', 'mode': 'auto',
            'entries': [{'id': r['id'], 'version': r['version']} for r in before]}
    preview = client.post(schedule + f'/tasks/{tid}/range/preview', headers=admin_headers, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['end_date'] == '2026-10-14'
    assert client.get(schedule, headers=admin_headers).json() == before
    policy = client.get(schedule + '/policy', headers=admin_headers).json()
    assert policy['task_overrides'][0]['workdays'] == 2
    body['preview_token'] = preview.json()['preview_token']
    saved = client.put(schedule + f'/tasks/{tid}/range', headers=admin_headers, json=body)
    assert saved.status_code == 200, saved.text
    assert client.get(schedule + '/policy', headers=admin_headers).json()['task_overrides'] == []
    generated = client.post(schedule + '/generate', headers=admin_headers)
    assert generated.status_code == 200, generated.text
    assert len({r['work_date'] for r in client.get(schedule, headers=admin_headers).json()}) == 5


def test_project_scale_is_saved_only_on_generation_and_reused_without_input(client, admin_headers, shortened_plan):
    pid, tid, _ = shortened_plan
    resize(client, admin_headers, pid, tid, '2026-10-08', '2026-10-09', mode='auto')
    schedule = f"/api/projects/{pid}/schedule"
    preview = client.get(schedule + '/preview', headers=admin_headers, params={'duration_scale': .5})
    assert preview.status_code == 200, preview.text
    assert client.get(schedule + '/policy', headers=admin_headers).json()['duration_scale'] == 1
    saved = client.post(schedule + '/generate', headers=admin_headers, json={'duration_scale': .5})
    assert saved.status_code == 200, saved.text
    assert client.get(schedule + '/policy', headers=admin_headers).json()['duration_scale'] == .5
    repeated = client.post(schedule + '/generate', headers=admin_headers)
    assert repeated.status_code == 200 and repeated.json()['duration_scale'] == .5
    assert len({r['work_date'] for r in client.get(schedule, headers=admin_headers).json()}) == 3


def test_manual_fractional_quantity_regenerates_at_worker_precision(client, admin_headers, shortened_plan):
    pid, tid, _ = shortened_plan
    with SessionLocal() as db:
        db.get(Task, tid).target_quantity = 1; db.commit()
    schedule = f"/api/projects/{pid}/schedule"
    generated = client.post(schedule + '/generate', headers=admin_headers)
    assert generated.status_code == 200, generated.text
    resize(client, admin_headers, pid, tid, '2026-10-12', '2026-10-14')
    repeated = client.post(schedule + '/generate', headers=admin_headers)
    assert repeated.status_code == 200, repeated.text
    rows = client.get(schedule, headers=admin_headers).json()
    assert [r['planned_quantity'] for r in rows] == [.33, .33, .34]
    assert len({r['work_date'] for r in rows}) == 3 and sum(r['planned_quantity'] for r in rows) == pytest.approx(1)


def legacy_range(pid, tid):
    """Simulate the exact old persisted audit, not dates alone."""
    with SessionLocal() as db:
        db.query(TaskDurationOverride).filter_by(task_id=tid).delete()
        log = db.query(ChangeLog).filter_by(project_id=pid, entity_id=tid, action='schedule_range').one()
        log.new_value = {key: log.new_value[key] for key in ('start_date','end_date','distribution')}
        db.commit()
        return log.id


def test_legacy_evidenced_resize_is_read_only_in_preview_and_recovers_on_generate(client, admin_headers, shortened_plan):
    pid, tid, _ = shortened_plan
    log_id = legacy_range(pid, tid)
    schedule = f'/api/projects/{pid}/schedule'
    policy = client.get(schedule+'/policy', headers=admin_headers).json()
    assert policy['task_overrides'][0]['workdays'] == 2
    preview = client.get(schedule+'/preview', headers=admin_headers)
    assert preview.status_code == 200 and preview.json()['after'] == 2
    with SessionLocal() as db:
        assert db.get(TaskDurationOverride,tid) is None
    generated = client.post(schedule+'/generate',headers=admin_headers)
    assert generated.status_code == 200 and generated.json()['tasks'][0]['duration_recovered']
    with SessionLocal() as db:
        assert db.get(TaskDurationOverride,tid).recovered_from_log_id == log_id


@pytest.mark.parametrize('ambiguity',['same_span','gap','unit','rest_change','timestamp_tie','missing_message','unknown_mode'])
def test_ambiguous_old_audit_does_not_guess_an_override(client,admin_headers,shortened_plan,ambiguity):
    pid,tid,actor=shortened_plan
    log_id=legacy_range(pid,tid)
    with SessionLocal() as db:
        log=db.get(ChangeLog,log_id)
        if ambiguity=='same_span':log.old_value={'start_date':'2026-10-08','end_date':'2026-10-09','entries':5}
        if ambiguity=='gap':
            new=dict(log.new_value);new['end_date']='2026-10-12'
            new['distribution']=[dict(r,work_date='2026-10-12' if r['work_date']=='2026-10-09' else r['work_date']) for r in new['distribution']]
            log.new_value=new
        if ambiguity=='unit':db.get(Task,tid).unit='米'
        if ambiguity=='missing_message':log.detail=None
        if ambiguity=='unknown_mode':log.new_value={**log.new_value,'mode':'unknown'}
        if ambiguity=='rest_change':
            from datetime import timedelta
            db.add(ChangeLog(project_id=pid,entity_type='project',entity_id=pid,action='update',operator_id=actor,
                             old_value={'rest_mode':'none'},new_value={'rest_mode':'two'},created_at=log.created_at+timedelta(seconds=1)))
        if ambiguity=='timestamp_tie':
            db.add(ChangeLog(project_id=pid,entity_type='task',entity_id=tid,action='schedule_range',operator_id=actor,
                             old_value=log.old_value,new_value=log.new_value,created_at=log.created_at))
        db.commit()
    policy=client.get(f'/api/projects/{pid}/schedule/policy',headers=admin_headers).json()
    assert policy['task_overrides']==[] and policy['recovery_warnings']
    with SessionLocal() as db:assert db.get(TaskDurationOverride,tid) is None


def test_automatic_tombstone_blocks_historical_resize_recovery(client,admin_headers,shortened_plan):
    pid,tid,_=shortened_plan
    legacy_range(pid,tid)
    resize(client,admin_headers,pid,tid,'2026-10-08','2026-10-09',mode='auto')
    schedule=f'/api/projects/{pid}/schedule'
    for _ in range(2):
        r=client.post(schedule+'/generate',headers=admin_headers)
        assert r.status_code==200 and r.json()['tasks'][0]['duration_source']=='automatic'
        assert len({row['work_date'] for row in client.get(schedule,headers=admin_headers).json()})==5
    with SessionLocal() as db:assert not db.get(TaskDurationOverride,tid).is_active


def test_shift_preserves_manual_budget_and_restore_rechecks_policy_token(client,admin_headers,shortened_plan):
    pid,tid,_=shortened_plan
    resize(client,admin_headers,pid,tid,'2026-10-12','2026-10-13',mode='shift')
    schedule=f'/api/projects/{pid}/schedule'
    policy=client.get(schedule+'/policy',headers=admin_headers).json()
    assert policy['task_overrides'][0]['workdays']==2 and policy['task_overrides'][0]['baseline_quantity']==10
    rows=client.get(schedule,headers=admin_headers).json()
    body={'start_date':'2026-10-12','end_date':'2026-10-13','mode':'auto',
          'entries':[{'id':r['id'],'version':r['version']} for r in rows]}
    preview=client.post(schedule+f'/tasks/{tid}/range/preview',headers=admin_headers,json=body)
    assert preview.status_code==200,preview.text
    body['preview_token']=preview.json()['preview_token']
    # No entry changes: changing only the saved policy still invalidates preview.
    with SessionLocal() as db:
        override=db.get(TaskDurationOverride,tid);override.version+=1;db.commit()
    saved=client.put(schedule+f'/tasks/{tid}/range',headers=admin_headers,json=body)
    assert saved.status_code==409 and client.get(schedule,headers=admin_headers).json()==rows
    assert client.get(schedule+'/policy',headers=admin_headers).json()['task_overrides']


@pytest.mark.parametrize('protection',['lock','confirmed','reported'])
def test_repeated_generation_preserves_execution_records_with_manual_budget(client,admin_headers,shortened_plan,protection):
    from app.models import DailyProgress
    pid,tid,actor=shortened_plan
    with SessionLocal() as db:
        rows=db.query(ScheduleEntry).filter_by(task_id=tid).all()
        for row in rows:
            if protection=='lock':row.is_locked=True
            if protection=='confirmed':row.is_confirmed=True
            if protection=='reported':db.add(DailyProgress(project_id=pid,task_id=tid,schedule_entry_id=row.id,
                                                          user_id=actor,work_date=row.work_date,completed_quantity=0,client_uuid=row.id))
        db.commit()
    schedule=f'/api/projects/{pid}/schedule'
    before=client.get(schedule,headers=admin_headers).json()
    r=client.post(schedule+'/generate',headers=admin_headers)
    assert r.status_code==200,r.text
    assert client.get(schedule,headers=admin_headers).json()==before


def test_scale_version_rejects_stale_confirmation_without_mutating_entries(client,admin_headers,shortened_plan):
    pid,_,_=shortened_plan
    schedule=f'/api/projects/{pid}/schedule'
    preview=client.get(schedule+'/preview',headers=admin_headers,params={'duration_scale':.5}).json()
    r=client.post(schedule+'/generate',headers=admin_headers,json={'duration_scale':.75})
    assert r.status_code==200,r.text
    before=client.get(schedule,headers=admin_headers).json()
    stale=client.post(schedule+'/generate',headers=admin_headers,json={'duration_scale':.5,'policy_version':preview['policy_version']})
    assert stale.status_code==409 and client.get(schedule,headers=admin_headers).json()==before


def test_partial_protected_work_reserves_quantity_and_only_remaining_budget_is_new(client,admin_headers,shortened_plan):
    pid,tid,_=shortened_plan
    with SessionLocal() as db:
        first=db.query(ScheduleEntry).filter_by(task_id=tid).order_by(ScheduleEntry.work_date,ScheduleEntry.id).first()
        first.planned_quantity=5;first.is_confirmed=True
        kept_id,kept_date=first.id,first.work_date.isoformat();db.commit()
    schedule=f'/api/projects/{pid}/schedule'
    generated=client.post(schedule+'/generate',headers=admin_headers)
    assert generated.status_code==200,generated.text
    rows=client.get(schedule,headers=admin_headers).json()
    kept=next(row for row in rows if row['id']==kept_id)
    assert kept['is_confirmed'] and kept['planned_quantity']==5 and kept['work_date']==kept_date
    new=[row for row in rows if row['id']!=kept_id]
    assert len(new)==1 and new[0]['planned_quantity']==5 and sum(row['planned_quantity'] for row in rows)==10


def test_manual_sparse_small_quantity_keeps_positive_endpoints_and_budget(client,admin_headers,shortened_plan):
    pid,tid,_=shortened_plan
    with SessionLocal() as db:db.get(Task,tid).target_quantity=.02;db.commit()
    schedule=f'/api/projects/{pid}/schedule'
    assert client.post(schedule+'/generate',headers=admin_headers).status_code==200
    resize(client,admin_headers,pid,tid,'2026-10-12','2026-10-14')
    generated=client.post(schedule+'/generate',headers=admin_headers)
    assert generated.status_code==200,generated.text
    rows=client.get(schedule,headers=admin_headers).json()
    assert [row['planned_quantity'] for row in rows]==[.01,.01]
    assert generated.json()['tasks'][0]['new_days']==3
    assert [row['work_date'] for row in rows]==['2026-10-08','2026-10-12']


def test_auto_restore_rejects_worker_and_new_execution_without_clearing_intent(client,admin_headers,worker_headers,shortened_plan):
    from app.models import DailyProgress
    pid,tid,actor=shortened_plan
    schedule=f'/api/projects/{pid}/schedule';rows=client.get(schedule,headers=admin_headers).json()
    body={'mode':'auto','start_date':'2026-10-12','end_date':'2026-10-09',
          'entries':[{'id':row['id'],'version':row['version']} for row in rows]}
    path=schedule+f'/tasks/{tid}/range'
    denied=client.post(path+'/preview',headers=worker_headers,json=body)
    assert denied.status_code==403
    preview=client.post(path+'/preview',headers=admin_headers,json=body)
    assert preview.status_code==200,preview.text
    body['preview_token']=preview.json()['preview_token']
    with SessionLocal() as db:
        row=db.get(ScheduleEntry,rows[0]['id'])
        db.add(DailyProgress(project_id=pid,task_id=tid,schedule_entry_id=row.id,user_id=actor,
                             work_date=row.work_date,completed_quantity=0,client_uuid='execution-after-auto-preview'))
        db.commit()
    at_write=client.get(schedule,headers=admin_headers).json()
    rejected=client.put(path,headers=admin_headers,json=body)
    assert rejected.status_code==400 and client.get(schedule,headers=admin_headers).json()==at_write
    with SessionLocal() as db:assert db.get(TaskDurationOverride,tid).is_active
