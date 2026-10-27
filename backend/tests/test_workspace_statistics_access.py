"""历史统计分组、人员候选池及 AI 状态读取权限。"""



def _project_with_report(client, pm_headers, worker_headers):
    """真实旧版数量行作为只读历史夹具，不调用已退役的数量填报写入口。"""
    from datetime import date
    from app.db import SessionLocal
    from app.models import Project, Phase, Task, DailyProgress
    response = client.post('/api/projects', headers=pm_headers, json={
        'name': '历史统计分组', 'start_date': '2026-08-01', 'end_date': '2026-09-30', 'new_vehicles': False})
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    worker_id = client.get('/api/auth/me', headers=worker_headers).json()['id']
    with SessionLocal() as db:
        project = db.get(Project, pid); project.members = [*project.members, worker_id]
        phase = Phase(project_id=pid, name='实施工作'); db.add(phase); db.flush()
        task = Task(project_id=pid, phase_id=phase.id, name='原数量工作', quantity_type='fixed', target_quantity=2, unit='台')
        db.add(task); db.flush()
        db.add(DailyProgress(project_id=pid, task_id=task.id, user_id=worker_id,
            work_date=date(2026, 8, 6), completed_quantity=1, note='原始历史事实', client_uuid='legacy-stats-0001'))
        db.commit()
    return pid

def test_retired_quantity_statistics_preserve_named_original_reports(client, pm_headers, worker_headers):
    from app.db import SessionLocal
    from app.models import DailyProgress, FieldOperation
    pid = _project_with_report(client, pm_headers, worker_headers)
    with SessionLocal() as db:
        source=db.query(DailyProgress).filter_by(project_id=pid).one(); tid=source.task_id
        before=tuple(getattr(source, col.name) for col in source.__table__.columns)
    assert client.get('/api/dashboard/stats', headers=pm_headers).status_code == 410
    response=client.get(f'/api/projects/{pid}/work-items/{tid}/history', headers=pm_headers)
    assert response.status_code == 200, response.text
    history=response.json()
    assert history['read_only'] and history['unit']=='台'
    assert history['reports'][0]['user_name']=='现场工程师A'
    assert history['reports'][0]['completed_quantity']==1
    with SessionLocal() as db:
        source=db.query(DailyProgress).filter_by(project_id=pid).one()
        assert tuple(getattr(source, col.name) for col in source.__table__.columns)==before
        assert db.query(FieldOperation).filter_by(project_id=pid).count()==0

def test_original_units_remain_separate_without_live_quantity_workload(client, pm_headers, worker_headers):
    from datetime import date
    from app.db import SessionLocal
    from app.models import Task, DailyProgress
    pid = _project_with_report(client, pm_headers, worker_headers)
    with SessionLocal() as db:
        original=db.query(DailyProgress).filter_by(project_id=pid).one()
        first=db.get(Task, original.task_id); first_id=first.id
        second=Task(project_id=pid, phase_id=first.phase_id, name='原米数工作', quantity_type='fixed', target_quantity=5, unit='米')
        db.add(second); db.flush(); second_id=second.id
        db.add(DailyProgress(project_id=pid, task_id=second.id, user_id=original.user_id,
            work_date=date(2026,8,6), completed_quantity=0.5, note='另一计量单位来源', client_uuid='legacy-stats-metres'))
        db.commit()
    assert client.get('/api/dashboard/stats', headers=pm_headers).status_code == 410
    first=client.get(f'/api/projects/{pid}/work-items/{first_id}/history', headers=pm_headers).json()
    second=client.get(f'/api/projects/{pid}/work-items/{second_id}/history', headers=pm_headers).json()
    assert (first['unit'], first['completed_quantity'])==('台',1)
    assert (second['unit'], second['completed_quantity'])==('米',0.5)
    assert first['reports'][0]['user_name']==second['reports'][0]['user_name']=='现场工程师A'
    current=client.get('/api/dashboard/statistics', headers=pm_headers)
    assert current.status_code == 200, current.text
    assert not {'workload','effort','person_days','quantities_by_unit'}.intersection(current.json())

def test_people_weeks_allow_technician(client, tech_headers):
    assert client.get('/api/dashboard/assignment-pool', headers=tech_headers).status_code == 410
    response=client.get('/api/people/weeks', headers=tech_headers, params={'scope':'team'})
    assert response.status_code == 200, response.text

def test_people_team_weeks_remain_blocked_for_worker(client, worker_headers):
    assert client.get('/api/dashboard/assignment-pool', headers=worker_headers).status_code == 410
    response=client.get('/api/people/weeks', headers=worker_headers, params={'scope':'team'})
    assert response.status_code == 403

def test_ai_status_is_readable_by_all_authenticated_roles(client, admin_headers, pm_headers, worker_headers, tech_headers, lead_headers):
    """T021：/ai-projects/status 对非 admin/pm 角色也应 200（不误显示为未配置）。

    director/lead/technician/worker 拿到 403 会被前端 /pm/ai 误判为「AI 未配置」。
    """
    for headers in (admin_headers, pm_headers, worker_headers, tech_headers, lead_headers):
        r = client.get('/api/ai-projects/status', headers=headers)
        assert r.status_code == 200, r.status_code
        assert 'available' in r.json() and 'providers' in r.json()
