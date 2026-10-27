"""Report quantities preserve units, full-period scope and signed adjustments."""
from datetime import date

import pytest

from app.db import SessionLocal
from app.models import DailyProgress, Notification, Project, Task, User
from app.services.progress import project_progress_tree
from app.services.report_scheduler import generate_and_notify_weekly_report
from tests.test_project_lifecycle_boundaries import project, task_entry


def _mixed_project(client, pm_headers):
    pid = project(client, pm_headers, '分单位报告回归')
    tasks = {unit: task_entry(pid, name=f'工作-{unit}')[0] for unit in ('台', '米', '项')}
    with SessionLocal() as db:
        people = db.query(User).filter(User.role == 'worker').order_by(User.id).all()[:2]
        for person in people:
            person.display_name = '同名现场人员'
        for unit, tid in tasks.items():
            task = db.get(Task, tid)
            task.unit = f' {unit} ' if unit == '米' else unit
            task.target_quantity = 10
        for index, (unit, person_index, quantity, work_date) in enumerate([
            ('台', 0, 2, date(2026, 10, 5)), ('台', 0, -1, date(2026, 10, 6)),
            ('米', 0, 2, date(2026, 10, 5)), ('项', 1, 1, date(2026, 10, 5)),
            ('台', 0, 7, date(2026, 9, 30)),
        ]):
            db.add(DailyProgress(project_id=pid, task_id=tasks[unit], user_id=people[person_index].id,
                                 work_date=work_date, completed_quantity=quantity,
                                 client_uuid=f'report-units-{index}', source='admin' if quantity < 0 else 'worker'))
        db.commit()
        ids = [person.id for person in people]
        expected_progress = project_progress_tree(db, pid)
    return pid, ids, expected_progress


@pytest.mark.parametrize('period', ['week', 'month'])
def test_report_groups_period_and_people_by_unit_without_changing_legacy_progress(client, pm_headers, period):
    pid, people, expected_progress = _mixed_project(client, pm_headers)
    response = client.get(f'/api/projects/{pid}/report', headers=pm_headers,
                          params={'period': period, 'ref_date': '2026-10-06'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['summary']['quantities_by_unit'] == [
        {'unit': '台', 'quantity': 1}, {'unit': '米', 'quantity': 2}, {'unit': '项', 'quantity': 1}]
    assert data['summary']['completed_quantity'] == 4  # Old clients keep their numeric DTO.
    assert data['summary']['report_count'] == 4
    assert data['summary']['person_count'] == 2
    by_person = {row['user_id']: row for row in data['per_person']}
    assert by_person[people[0]]['quantities_by_unit'] == [{'unit': '台', 'quantity': 1}, {'unit': '米', 'quantity': 2}]
    assert by_person[people[1]]['quantities_by_unit'] == [{'unit': '项', 'quantity': 1}]
    assert by_person[people[0]]['quantity'] == 3
    assert data['progress']['percent'] == expected_progress['percent']
    assert data['progress']['completed'] == expected_progress['completed']
    assert data['progress']['target'] == expected_progress['target']
    assert data['progress']['quantities_by_unit'] == expected_progress['quantities_by_unit']
    assert {row['unit'] for row in data['completed_items']} == {'台', '米', '项'}
    assert any(row['quantity'] == -1 for row in data['completed_items'])


def test_report_unit_summaries_include_rows_beyond_the_detail_limit_and_default_blank_units(client, pm_headers):
    pid = project(client, pm_headers)
    tai = task_entry(pid)[0]
    blank = task_entry(pid, name='缺省单位工作')[0]
    with SessionLocal() as db:
        uid = db.get(Project, pid).manager
        db.get(Task, tai).unit = '台'
        db.get(Task, blank).unit = '  '
        for index in range(101):
            db.add(DailyProgress(project_id=pid, task_id=tai, user_id=uid, work_date=date(2026, 10, 5),
                                 completed_quantity=0.01, client_uuid=f'report-limit-{index}'))
        db.add(DailyProgress(project_id=pid, task_id=blank, user_id=uid, work_date=date(2026, 10, 5),
                             completed_quantity=0.2, client_uuid='report-limit-default-unit'))
        db.commit()
    response = client.get(f'/api/projects/{pid}/report', headers=pm_headers,
                          params={'period': 'week', 'ref_date': '2026-10-05'})
    assert response.status_code == 200, response.text
    data = response.json()
    expected = [{'unit': '台', 'quantity': 1.01}, {'unit': '项', 'quantity': 0.2}]
    assert len(data['completed_items']) == 100
    assert data['summary']['report_count'] == 102
    assert data['summary']['quantities_by_unit'] == expected
    assert data['per_person'][0]['quantities_by_unit'] == expected


def test_report_empty_period_has_empty_unit_groups(client, pm_headers):
    pid, _, _ = _mixed_project(client, pm_headers)
    response = client.get(f'/api/projects/{pid}/report', headers=pm_headers,
                          params={'period': 'week', 'ref_date': '2026-11-02'})
    assert response.status_code == 200, response.text
    assert response.json()['summary']['quantities_by_unit'] == []
    assert response.json()['summary']['completed_quantity'] == 0
    assert response.json()['per_person'] == []


def test_scheduled_report_notification_preserves_each_unit_and_signed_net_quantity(client, pm_headers):
    pid, _, _ = _mixed_project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).status = 'executing'
        db.commit()
        result = generate_and_notify_weekly_report(db, ref_date=date(2026, 10, 13))
        db.commit()
        notice = db.query(Notification).filter_by(project_id=pid, ntype='report').one()
        assert result['notified'] == 1
        assert '本周期完成量 1 台、2 米、1 项' in notice.content
        assert '填报 4 条 · 2 人' in notice.content
        assert '完成 4' not in notice.content
