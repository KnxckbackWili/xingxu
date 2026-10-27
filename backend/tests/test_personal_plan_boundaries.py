"""本人计划与项目终态边界。"""

from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Project, ScheduleEntry, Task
from tests.test_project_lifecycle_boundaries import project, task_entry


@pytest.mark.parametrize('status', ['completed', 'archived'])
@pytest.mark.parametrize('operation', ['create', 'edit'])
def test_personal_calendar_cannot_bypass_terminal_schedule_guard(client, pm_headers, status, operation):
    pid = project(client, pm_headers)
    tid, eid, _ = task_entry(pid)
    with SessionLocal() as db:
        db.get(Project, pid).status = status
        db.commit()
    if operation == 'create':
        result = client.post('/api/dashboard/people-plan/self', headers=pm_headers, json={
            'project_id': pid, 'task_id': tid, 'work_date': '2026-09-02', 'planned_quantity': 1,
        })
    else:
        result = client.put(f'/api/dashboard/people-plan/{eid}/self', headers=pm_headers, json={
            'work_date': '2026-09-02', 'planned_quantity': 1, 'notes': '旧页面修改', 'version': 0,
        })
    assert result.status_code == 400, result.text
    with SessionLocal() as db:
        assert db.query(ScheduleEntry).filter_by(project_id=pid).count() == 1
        assert db.get(ScheduleEntry, eid).work_date == date(2026, 9, 1)


def test_report_defaults_to_project_local_calendar_date(client, pm_headers, monkeypatch):
    pid = project(client, pm_headers)
    monkeypatch.setattr('app.time_utils.project_today', lambda tz: date(2026, 9, 2))
    result = client.get(f'/api/projects/{pid}/report', headers=pm_headers)
    assert result.status_code == 200, result.text
    assert result.json()['period_label'] == '2026-08-31 ~ 2026-09-06'
    assert result.json()['generated_at'] == '2026-09-02'


@pytest.mark.parametrize('non_executable', ['reminder', 'manual_complete'])
def test_self_calendar_cannot_schedule_non_executable_task(client, pm_headers, non_executable):
    from app.models import Phase
    pid = project(client, pm_headers)
    tid, _, phase_id = task_entry(pid)
    with SessionLocal() as db:
        if non_executable == 'reminder':
            db.get(Phase, phase_id).name = '项目准备'
        else:
            db.get(Task, tid).manually_completed = True
        db.commit()
    result = client.post('/api/dashboard/people-plan/self', headers=pm_headers,
                         json={'project_id': pid, 'task_id': tid, 'work_date': '2026-09-02',
                               'planned_quantity': 1})
    assert result.status_code == 400, result.text
    with SessionLocal() as db:
        assert db.query(ScheduleEntry).filter_by(project_id=pid).count() == 1
