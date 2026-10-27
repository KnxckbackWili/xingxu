"""报表周期、当地日期、真实人员和当前事实。"""

from datetime import date
import pytest
from app.db import SessionLocal
from app.models import DailyProgress, Issue, Project, ScheduleEntry, User
from tests.test_project_lifecycle_boundaries import project, task_entry


def test_weekly_report_omits_cancelled_future_and_overdue_plans(client, pm_headers):
    pid = project(client, pm_headers)
    tid, old, _ = task_entry(pid, status='skipped')
    with SessionLocal() as db:
        db.get(ScheduleEntry, old).work_date = date(2026, 8, 31)
        db.add(ScheduleEntry(project_id=pid, task_id=tid, work_date=date(2026, 9, 8),
                             planned_quantity=2, status='skipped'))
        db.commit()
    result = client.get(f'/api/projects/{pid}/report', headers=pm_headers,
                        params={'period': 'week', 'ref_date': '2026-09-02'})
    assert result.status_code == 200, result.text
    assert result.json()['next_plan'] == []
    assert result.json()['risks'] == []


def test_report_keeps_different_people_with_same_name_separate(client, pm_headers):
    pid = project(client, pm_headers)
    tid, _, _ = task_entry(pid)
    with SessionLocal() as db:
        people = db.query(User).filter(User.role == 'worker').all()[:2]
        for index, person in enumerate(people):
            person.display_name = '同名人员'
            db.add(DailyProgress(project_id=pid, task_id=tid, user_id=person.id,
                                 work_date=date(2026, 9, 2), completed_quantity=1,
                                 client_uuid=f'round6-name-{index}'))
        db.commit()
    result = client.get(f'/api/projects/{pid}/report', headers=pm_headers,
                        params={'period': 'week', 'ref_date': '2026-09-02'})
    assert result.status_code == 200, result.text
    assert result.json()['summary']['person_count'] == 2
    assert len(result.json()['per_person']) == 2
    assert len({row['user_id'] for row in result.json()['per_person']}) == 2


@pytest.mark.parametrize('path', ['overview', 'stats', 'decision-view'])
def test_management_views_share_quality_adjusted_project_progress(client, pm_headers, path):
    from app.models import CheckItem
    from app.services.progress import project_progress_tree
    from tests.test_lifecycle_write_integrity import completeable_project
    pid, _, cid = completeable_project(client, pm_headers)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = 'executing'
        p.end_date = date(2026, 1, 1)
        db.get(CheckItem, cid).is_done = False
        db.get(CheckItem, cid).failed = True
        db.commit()
        expected = project_progress_tree(db, pid)['percent']
        assert expected == 99
    result = client.get('/api/dashboard/' + path, headers=pm_headers)
    assert result.status_code == 200, result.text
    rows = result.json()['risks' if path == 'decision-view' else 'projects']
    key = 'project_id' if path == 'decision-view' else 'id'
    row = next((row for row in rows if row[key] == pid), None)
    assert row is not None, result.json()
    assert row['percent'] == expected


def test_on_time_rate_uses_the_matching_schedule_and_work_date(client, pm_headers):
    pid = project(client, pm_headers)
    tid, eid, _ = task_entry(pid)
    with SessionLocal() as db:
        old = db.get(ScheduleEntry, eid)
        old.planned_quantity = 1
        second = ScheduleEntry(project_id=pid, task_id=tid, work_date=date(2026, 9, 2),
                               planned_quantity=1, assignee_id=db.get(Project, pid).manager)
        db.add(second)
        db.add(DailyProgress(project_id=pid, task_id=tid, schedule_entry_id=eid,
                             user_id=db.get(Project, pid).manager, work_date=date(2026, 9, 2),
                             completed_quantity=1, client_uuid='late-linked-report'))
        db.commit()
    result = client.get('/api/dashboard/metrics', headers=pm_headers)
    assert result.status_code == 200, result.text
    assert result.json()['on_time_rate'] == 0


def test_zero_quantity_duration_row_is_not_unfinished_quantity(client, pm_headers):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    with SessionLocal() as db:
        db.get(ScheduleEntry, eid).planned_quantity = 0
        db.commit()
    result = client.get(f'/api/projects/{pid}/overdue', headers=pm_headers)
    assert result.status_code == 200, result.text
    assert result.json()['count'] == 0


def test_worker_overdue_aggregates_each_task_once_and_uses_project_date(client, pm_headers, worker_headers, monkeypatch):
    pid = project(client, pm_headers)
    tid, eid, _ = task_entry(pid)
    worker = client.get('/api/auth/me', headers=worker_headers).json()['id']
    assert client.put(f'/api/projects/{pid}', headers=pm_headers,
                      json={'members': [worker]}).status_code == 200
    with SessionLocal() as db:
        db.get(Project, pid).status = 'executing'
        db.get(ScheduleEntry, eid).planned_quantity = 1
        db.add(ScheduleEntry(project_id=pid, task_id=tid, work_date=date(2026, 9, 2), planned_quantity=1))
        db.add(ScheduleEntry(project_id=pid, task_id=tid, work_date=date(2026, 9, 3), planned_quantity=1))
        db.commit()
    monkeypatch.setattr('app.time_utils.project_today', lambda tz: date(2026, 9, 3))
    result = client.get('/api/worker/overdue', headers=worker_headers)
    assert result.status_code == 200, result.text
    assert result.json()['count'] == 1
    row = result.json()['items'][0]
    assert row['planned_by_now'] == 2
    assert row['last_date'] == '2026-09-02' and row['overdue_days'] == 1


def test_report_issue_period_uses_local_midnight_not_utc_midnight(client, pm_headers):
    from datetime import datetime
    pid = project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).timezone = 'Asia/Shanghai'
        # Monday 04:30 at the site, still Sunday in the UTC storage column.
        moment = datetime(2026, 9, 6, 20, 30)
        db.add(Issue(project_id=pid, title='当地周一新增', status='open', created_at=moment, reporter_id=db.get(Project, pid).manager))
        db.add(Issue(project_id=pid, title='当地周一解决', status='resolved',
                     created_at=moment, resolved_at=moment, reporter_id=db.get(Project, pid).manager))
        db.commit()
    report = client.get(f'/api/projects/{pid}/report', headers=pm_headers,
                        params={'ref_date': '2026-09-07'})
    assert report.status_code == 200, report.text
    assert report.json()['summary']['issues_opened'] == 2
    assert report.json()['summary']['issues_resolved'] == 1
    assert all(row['created_at'] == '2026-09-07' for row in report.json()['opened_issues'])
