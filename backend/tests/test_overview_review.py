"""Overview must use the same overdue definition as the dedicated action list."""
from datetime import date
from tests.test_project_timezone import _create_project, _schedule_project


def test_overview_excludes_completed_entries_and_preserves_stage_context(client, pm_headers):
    from app.db import SessionLocal
    from app.models import ScheduleEntry, DailyProgress
    p = _create_project(client, pm_headers)
    _schedule_project(client, pm_headers, p['id'])
    with SessionLocal() as db:
        entries = db.query(ScheduleEntry).filter_by(project_id=p['id']).all()
        assert len(entries) >= 2
        for entry in entries:
            entry.work_date = date(2020, 1, 1)
        completed = entries[0]
        completed_id = completed.id
        db.add(DailyProgress(project_id=p['id'], task_id=completed.task_id,
                             schedule_entry_id=completed.id, work_date=completed.work_date,
                             user_id='user-worker-001', completed_quantity=completed.planned_quantity,
                             client_uuid='overview-completed'))
        db.commit()
    detail = client.get(f"/api/projects/{p['id']}/overdue", headers=pm_headers)
    overview = client.get(f"/api/projects/{p['id']}/overview", headers=pm_headers)
    assert overview.status_code == 200, overview.text
    rows = overview.json()['overdue']['items']
    assert rows
    assert all(row.get('entry_id', row.get('id')) != completed_id for row in rows)
    assert {row['entry_id'] for row in rows} == {row['entry_id'] for row in detail.json()['items']}
    assert all('phase_relation' in row and 'stage_relevance' in row for row in rows)


def test_overdue_uses_project_day(client, pm_headers, monkeypatch):
    from app.db import SessionLocal
    from app.models import ScheduleEntry
    import app.time_utils as time_utils
    p = _create_project(client, pm_headers, timezone='Europe/Moscow')
    _schedule_project(client, pm_headers, p['id'])
    with SessionLocal() as db:
        for entry in db.query(ScheduleEntry).filter_by(project_id=p['id']):
            entry.work_date = date(2020, 1, 1)
        db.commit()
    monkeypatch.setattr(time_utils, 'project_today', lambda tz: date(2020, 1, 1))
    r = client.get(f"/api/projects/{p['id']}/overdue", headers=pm_headers)
    assert r.status_code == 200
    assert r.json()['items'] == []
