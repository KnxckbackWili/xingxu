"""T41 official fixtures, explicit coverage, maintenance and schedule semantics."""
from datetime import date, timedelta

import pytest

from app.db import SessionLocal
from app.models import ChangeLog, HolidayCalendar
from app.services.holidays import calendar_in_range, calendar_snapshot, calendar_year, is_holiday
from app.services.weekly_plans import weeks_metadata


def payload(year=2027, **changes):
    # Deliberately synthetic; these dates are not shipped as 2027 official data.
    result = dict(year=year, holidays=[f'{year}-01-01'], workdays=[f'{year}-01-02'],
        source_name='仅测试的全年安排（非官方）', source_url='https://example.com/test-calendar',
        published_on='2026-10-01', note='synthetic fixture', complete=True, expected_version=0)
    return {**result, **changes}


def test_reviewed_official_dates_and_makeup_days():
    snapshot = calendar_snapshot()
    assert set(snapshot) == {2024, 2025, 2026}  # Never guess next year's calendar.
    assert calendar_year(2024)['published_on'] == '2023-10-25'
    assert calendar_year(2025)['published_on'] == '2024-11-12'
    assert calendar_year(2026)['published_on'] == '2025-11-04'
    assert not is_holiday(date(2024, 2, 9))  # Encouraged annual leave != national holiday.
    assert all(is_holiday(date(2026, 2, d)) for d in range(15, 24))
    assert snapshot[2024]['workdays'] == ['2024-02-04', '2024-02-18', '2024-04-07', '2024-04-28', '2024-05-11', '2024-09-14', '2024-09-29', '2024-10-12']
    assert snapshot[2025]['workdays'] == ['2025-01-26', '2025-02-08', '2025-04-27', '2025-09-28', '2025-10-11']
    assert snapshot[2026]['workdays'] == ['2026-01-04', '2026-02-14', '2026-02-28', '2026-05-09', '2026-09-20', '2026-10-10']
    for year, calendar in snapshot.items():
        assert calendar['source_kind'] == 'bundled_official'
        assert calendar['source_url'].startswith('https://www.gov.cn/')
        assert not set(calendar['holidays']) & set(calendar['workdays'])
        assert all(value.startswith(str(year)) for value in calendar['holidays'] + calendar['workdays'])


def test_missing_year_is_not_claimed_as_no_holidays():
    assert calendar_year(2027)['available'] is False
    coverage = calendar_in_range(date(2026, 9, 20), date(2028, 2, 1))
    assert coverage['missing_holiday_years'] == [2027, 2028]
    assert coverage['adjusted_work_dates'] == ['2026-09-20', '2026-10-10']
    assert '2026-10-01' in coverage['holiday_dates']
    assert {row['year'] for row in coverage['holiday_sources']} == {2026}
    assert calendar_in_range(None, None)['missing_holiday_years'] == []


def test_week_metadata_preserves_holiday_and_makeup_facts_without_daily_scheduling():
    weeks = weeks_metadata(None, date(2026, 2, 14), 3)
    assert [week['week_start'] for week in weeks] == ['2026-02-09', '2026-02-16', '2026-02-23']
    assert weeks[0]['holiday_days'] == ['2026-02-15']
    assert weeks[0]['makeup_workdays'] == ['2026-02-14']
    assert weeks[1]['holiday_days'] == [f'2026-02-{day:02}' for day in range(16, 23)]
    assert weeks[2]['holiday_days'] == ['2026-02-23']
    assert weeks[2]['makeup_workdays'] == ['2026-02-28']
    assert all(week['missing_holiday_years'] == [] for week in weeks)


def test_calendar_read_auth_and_missing_coverage(client, worker_headers):
    client.cookies.clear()
    assert client.get('/api/holiday-calendars/2027').status_code == 401
    response = client.get('/api/holiday-calendars?start_year=2026&end_year=2027', headers=worker_headers)
    assert response.status_code == 200
    assert [row['available'] for row in response.json()['years']] == [True, False]
    assert client.get('/api/holiday-calendars?start_year=2028&end_year=2027', headers=worker_headers).status_code == 422
    assert client.put('/api/holiday-calendars/2027', headers=worker_headers, json=payload()).status_code == 403


def test_maintenance_is_versioned_audited_and_visible_to_project_without_restarting(client, admin_headers, pm_headers):
    project = client.post('/api/projects', headers=pm_headers, json={'name': '跨年项目', 'start_date': '2026-12-01', 'end_date': '2027-03-01'}).json()
    pid = project['id']
    assert project['missing_holiday_years'] == [2027]
    response = client.put('/api/holiday-calendars/2027', headers=admin_headers, json=payload())
    assert response.status_code == 200, response.text
    assert response.json()['source_kind'] == 'maintained'
    assert response.json()['version'] == 1
    project = client.get(f'/api/projects/{pid}', headers=pm_headers).json()
    assert project['missing_holiday_years'] == []
    assert project['holiday_dates'] == ['2027-01-01']
    assert project['adjusted_work_dates'] == ['2027-01-02']
    assert project['status'] == 'preparing'
    with SessionLocal() as db:
        week = weeks_metadata(db, date(2027, 1, 1), 1)[0]
        assert week['holiday_days'] == ['2027-01-01']
        assert week['makeup_workdays'] == ['2027-01-02']
        assert week['missing_holiday_years'] == []
        audit = db.query(ChangeLog).filter_by(entity_type='holiday_calendar', entity_id='2027').one()
        assert audit.old_value['available'] is False
        assert audit.new_value['holidays'] == ['2027-01-01']
    # No stale process-global cache; a later update changes the next response.
    response = client.put('/api/holiday-calendars/2027', headers=admin_headers, json=payload(expected_version=1, holidays=['2027-01-03']))
    assert response.status_code == 200 and response.json()['version'] == 2
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['holiday_dates'] == ['2027-01-03']
    for stale in (0, 1):
        assert client.put('/api/holiday-calendars/2027', headers=admin_headers, json=payload(expected_version=stale)).status_code == 409
    assert client.get('/api/holiday-calendars/2027', headers=admin_headers).json()['holidays'] == ['2027-01-03']


@pytest.mark.parametrize('changes', [
    {'holidays': ['2026-01-01']}, {'holidays': ['2027-02-30']}, {'holidays': ['2027-1-01']},
    {'holidays': ['2027-01-01', '2027-01-01']}, {'holidays': []}, {'workdays': ['2027-01-01']},
    {'complete': False}, {'source_name': '   '}, {'source_url': 'javascript:alert(1)'},
    {'source_url': 'https://user:password@example.com/data'}, {'published_on': '2200-01-01'},
    {'unexpected': 'must not silently ignore source fields'},
])
def test_invalid_import_does_not_partially_write(client, admin_headers, changes):
    assert client.put('/api/holiday-calendars/2027', headers=admin_headers, json=payload(**changes)).status_code == 422
    assert client.get('/api/holiday-calendars/2027', headers=admin_headers).json()['available'] is False
    with SessionLocal() as db:
        assert db.query(HolidayCalendar).count() == 0
        assert db.query(ChangeLog).filter_by(entity_type='holiday_calendar').count() == 0


def test_target_year_and_explicit_permission_denial(client, admin_headers, pm_headers):
    assert client.put('/api/holiday-calendars/2028', headers=admin_headers, json=payload()).status_code == 422
    from app.models import User
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username='admin').one()
        admin.permission_overrides = {'system.holidays.manage': False}
        db.commit()
    assert client.put('/api/holiday-calendars/2027', headers=admin_headers, json=payload()).status_code == 403


def test_audit_failure_rolls_back_annual_data(client, admin_headers, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr('app.routers.holiday_calendars.log_change', fail)
    with pytest.raises(RuntimeError, match='audit unavailable'):
        client.put('/api/holiday-calendars/2027', headers=admin_headers, json=payload())
    with SessionLocal() as db:
        assert db.query(HolidayCalendar).count() == 0
