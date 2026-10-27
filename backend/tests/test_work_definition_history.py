"""工作快照及原日程填报来源保全。"""



def _project_with_member(client, pm_headers, worker_headers):
    r = client.post('/api/projects', headers=pm_headers, json={'name': '工作快照保全项目', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'})
    pid = r.json()['id']
    client.post(f'/api/projects/{pid}/vehicles', headers=pm_headers, json={'vehicle_type': '潜伏式', 'model_name': 'AGV-500', 'quantity': 2})
    client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': ['mod-03']})
    wid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    r = client.get(f'/api/projects/{pid}', headers=pm_headers)
    client.put(f'/api/projects/{pid}', headers=pm_headers, json={'members': [*r.json()['members'], wid]})
    return pid

def test_daily_regeneration_preserves_original_reports(client, pm_headers, worker_headers):
    """重排不能删除已有旧填报的条目，也不能改写原数量、日期及关联。"""
    from datetime import date
    from app.db import SessionLocal
    from app.models import DailyProgress, ScheduleEntry, Task, Module, Phase
    pid = _project_with_member(client, pm_headers, worker_headers)
    worker_id = client.get('/api/auth/me', headers=worker_headers).json()['id']
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='旧实施工作'); db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='原日程模块'); db.add(module); db.flush()
        task = Task(project_id=pid, module_id=module.id, name='旧数量工作',
            quantity_type='fixed', target_quantity=3, unit='台', standard_hours=8)
        db.add(task); db.flush()
        entry = ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2026, 8, 10),
            assignee_id=worker_id, planned_quantity=1.5, is_confirmed=False, notes='原未确认日程', version=4)
        db.add(entry); db.flush()
        report = DailyProgress(project_id=pid, task_id=task.id, schedule_entry_id=entry.id,
            work_date=entry.work_date, user_id=worker_id, completed_quantity=1, note='原填报说明', client_uuid='replan-keep-01')
        db.add(report); db.commit(); entry_id=entry.id; report_id=report.id
        original_entry = (entry.task_id, entry.assignee_id, entry.work_date, entry.planned_quantity, entry.notes, entry.version)
        original_report = (report.task_id, report.schedule_entry_id, report.work_date, report.user_id,
            report.completed_quantity, report.note, report.client_uuid, report.created_at)
    response = client.post(f'/api/projects/{pid}/schedule/generate', headers=pm_headers)
    assert response.status_code == 200, response.text
    entries = client.get(f'/api/projects/{pid}/schedule', headers=pm_headers).json()
    assert any(row['id'] == entry_id for row in entries)
    with SessionLocal() as db:
        entry=db.get(ScheduleEntry, entry_id); report=db.get(DailyProgress, report_id)
        assert (entry.task_id, entry.assignee_id, entry.work_date, entry.planned_quantity, entry.notes, entry.version) == original_entry
        assert (report.task_id, report.schedule_entry_id, report.work_date, report.user_id,
            report.completed_quantity, report.note, report.client_uuid, report.created_at) == original_report

def test_generate_preserves_project_snapshot_no_duplicate(client, pm_headers):
    """C2-6：模板改名后再次带入 → 保留项目任务原名，不覆盖现场计划也不重复。"""
    pid = client.post('/api/projects', headers=pm_headers, json={'name': '改名幂等项目', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}).json()['id']
    client.post(f'/api/projects/{pid}/vehicles', headers=pm_headers, json={'vehicle_type': '潜伏式', 'model_name': 'AGV-500', 'quantity': 2})
    client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': ['mod-03']})
    tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    names_before = {t['name'] for ph in tree for m in ph['modules'] for t in m['tasks']}
    assert '单车机械与导航调试' in names_before
    from app.db import SessionLocal
    from app.models import Task
    db = SessionLocal()
    try:
        tpl_task = db.get(Task, 'task-009')
        assert tpl_task is not None
        tpl_task.name = '单车机械与导航调试（改名后）'
        db.commit()
    finally:
        db.close()
    client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': ['mod-03']})
    tree2 = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    names_after = {t['name'] for ph in tree2 for m in ph['modules'] for t in m['tasks']}
    assert '单车机械与导航调试（改名后）' not in names_after
    assert '单车机械与导航调试' in names_after, '项目快照应保留，不随模板改名'
    count_after = sum((1 for ph in tree2 for m in ph['modules'] for t in m['tasks']))
    assert count_after == 5
