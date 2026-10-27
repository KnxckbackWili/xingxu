"""Overview must use the same overdue definition as the dedicated action list (v3: document deadlines)."""
from datetime import date, datetime
from tests.test_project_timezone import _create_project


def _legacy_past_schedule(pid):
    """Read-only legacy daily schedule rows in the past; they must never become overdue actions."""
    from app.db import SessionLocal
    from app.models import ScheduleEntry, Task
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=pid).first()
        db.add(ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2020, 1, 1), planned_quantity=1,
                             assignee_id='user-worker-001', status='planned', is_confirmed=True))
        db.commit()


def _generated_project(client, pm_headers, **kwargs):
    p = _create_project(client, pm_headers, **kwargs)
    assert client.post(f"/api/projects/{p['id']}/tasks/generate", headers=pm_headers,
                       json={"module_ids": ["mod-01"]}).status_code == 200
    return p


def test_overview_overdue_matches_document_action_list(client, pm_headers):
    from app.db import SessionLocal
    from app.models import ProjectDocument
    p = _generated_project(client, pm_headers)
    _legacy_past_schedule(p['id'])
    with SessionLocal() as db:
        row = db.query(ProjectDocument).filter_by(project_id=p['id'], status='pending').first()
        row.due_at = datetime(2020, 1, 1); db.commit(); overdue_id = row.id
    detail = client.get(f"/api/projects/{p['id']}/overdue", headers=pm_headers)
    overview = client.get(f"/api/projects/{p['id']}/overview", headers=pm_headers)
    assert detail.status_code == 200 and overview.status_code == 200, overview.text
    rows = overview.json()['overdue']['items']
    assert overdue_id in {row['document_id'] for row in rows}
    assert {row['document_id'] for row in rows} == {row['document_id'] for row in detail.json()['items']}
    assert overview.json()['overdue']['count'] == detail.json()['count']


def test_legacy_schedule_never_counts_as_overdue_and_timezone_is_reported(client, pm_headers):
    p = _generated_project(client, pm_headers, timezone='Europe/Moscow')
    _legacy_past_schedule(p['id'])
    r = client.get(f"/api/projects/{p['id']}/overdue", headers=pm_headers)
    assert r.status_code == 200
    body = r.json()
    assert body['timezone'] == 'Europe/Moscow'
    assert all('document_id' in item for item in body['items'])
