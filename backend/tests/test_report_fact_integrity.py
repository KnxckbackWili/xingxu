"""报表周期、当地日期、真实人员和当前事实。"""

from tests.lifecycle_helpers import versioned
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


def test_report_keeps_different_people_with_same_name_separate(client, pm_headers, worker_headers):
    from app.models import CheckItem
    from tests.test_worker import _setup
    pid = _setup(client, pm_headers)
    second = client.post('/api/auth/login', json={'username': 'worker2', 'password': 'worker123'})
    second_headers = {'Authorization': f"Bearer {second.json()['access_token']}"}
    with SessionLocal() as db:
        people = db.query(User).filter(User.username.in_(['worker1', 'worker2'])).all()
        for person in people:
            person.display_name = '同名人员'
        db.get(Project, pid).members = [person.id for person in people]
        checks = [(c.id, c.version or 0) for c in db.query(CheckItem).filter_by(project_id=pid).order_by(CheckItem.id).limit(2)]
        db.commit()
    for headers, (cid, version) in zip((worker_headers, second_headers), checks):
        r = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=headers, json={'is_done': True, 'version': version})
        assert r.status_code == 200, r.text
    result = client.get(f'/api/projects/{pid}/report', headers=pm_headers, params={'period': 'week'})
    assert result.status_code == 200, result.text
    assert result.json()['summary']['person_count'] == 2
    assert len(result.json()['per_person']) == 2
    assert len({row['user_id'] for row in result.json()['per_person']}) == 2


def test_zero_quantity_duration_row_is_not_unfinished_quantity(client, pm_headers):
    pid = project(client, pm_headers)
    _, eid, _ = task_entry(pid)
    with SessionLocal() as db:
        db.get(ScheduleEntry, eid).planned_quantity = 0
        db.commit()
    result = client.get(f'/api/projects/{pid}/overdue', headers=pm_headers)
    assert result.status_code == 200, result.text
    assert result.json()['count'] == 0


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
