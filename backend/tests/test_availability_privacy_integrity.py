"""人员不可用信息隐私与计划冲突范围。"""

from datetime import date, timedelta
import pytest
from fastapi import HTTPException


def test_private_events_defer_only_their_project_and_remain_owner_manageable(client, pm_headers, admin_headers):
    from datetime import timedelta
    from app.db import SessionLocal
    from app.models import Project, ProjectArchive, PersonalEvent
    from app.services.report_scheduler import purge_soft_deleted_projects
    from app.time_utils import utcnow
    ids = [client.post('/api/projects', headers=pm_headers, json={
        'name': name, 'start_date': '2026-01-01', 'end_date': '2026-12-31', 'new_vehicles': False}).json()['id']
        for name in ['Private calendar retention', 'Ordinary retention']]
    event = client.post('/api/dashboard/personal-events', headers=pm_headers, json={
        'project_id': ids[0], 'work_date': '2026-01-01', 'title': 'OWNER ONLY NOTE', 'notes': 'PRIVATE EVENT DETAILS'}).json()['event']
    with SessionLocal() as db:
        for pid in ids: db.get(Project, pid).deleted_at = utcnow()-timedelta(days=31)
        db.commit()
        result = purge_soft_deleted_projects(db); db.commit()
        assert result['purged'] == result['blocked'] == 0 and result['disabled']
        assert 'OWNER ONLY' not in str(result) and 'PRIVATE EVENT' not in str(result)
        assert db.get(Project, ids[0]) is not None and db.get(Project, ids[1]) is not None
        assert db.query(ProjectArchive).filter_by(project_id=ids[0]).count() == 0
    events = client.get('/api/dashboard/personal-events', headers=pm_headers).json()
    assert any(item['id'] == event['id'] for item in events)
    assert client.delete(f"/api/dashboard/personal-events/{event['id']}", headers=admin_headers).status_code == 404
    assert client.delete(f"/api/dashboard/personal-events/{event['id']}", headers=pm_headers).status_code == 200
    with SessionLocal() as db:
        assert purge_soft_deleted_projects(db)['purged'] == 0
        db.commit()
        assert db.get(Project, ids[0]) is not None


def _ids():
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        return {u.username: u.id for u in db.query(User).all()}


def _work(db, ids, *, name="人员审计项目", day=None, deleted=False,
          status="executing", members=None, assignee=None):
    from app.models import Project, ProjectMember, Phase, Module, Task, ScheduleEntry
    from app.time_utils import utcnow
    day = day or date.today()
    members = members if members is not None else [ids["worker1"], ids["worker2"]]
    project = Project(name=name, start_date=day, end_date=day + timedelta(days=30),
                      manager=ids["pm"], members=members, status=status,
                      created_by=ids["pm"],
                      deleted_at=utcnow() if deleted else None)
    db.add(project); db.flush()
    for uid in set([ids["pm"], *members]):
        db.add(ProjectMember(project_id=project.id, user_id=uid))
    phase = Phase(project_id=project.id, name="现场实施")
    db.add(phase); db.flush()
    module = Module(project_id=project.id, phase_id=phase.id, name="实施")
    db.add(module); db.flush()
    task = Task(project_id=project.id, module_id=module.id, name="调试", quantity_type="fixed",
                target_quantity=1, standard_hours=8)
    db.add(task); db.flush()
    entry = ScheduleEntry(project_id=project.id, task_id=task.id, work_date=day,
                          assignee_id=assignee or ids["worker1"], planned_quantity=1)
    db.add(entry); db.commit()
    return project.id


def _leave(client, headers, uid, *, start=None, end=None):
    today = date.today().isoformat()
    response = client.post(f"/api/users/{uid}/unavailability", headers=headers, json={
        "start_date": start or today, "end_date": end or today,
        "reason": "私人病假", "note": "私人医疗说明不可向同事公开",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_assignment_pool_excludes_deleted_project_schedule(client, pm_headers):
    from app.db import SessionLocal
    ids = _ids()
    with SessionLocal() as db:
        _work(db, ids, deleted=True)
    response = client.get("/api/dashboard/assignment-pool", headers=pm_headers)
    assert response.status_code == 200, response.text
    row = next(p for p in response.json()["items"] if p["id"] == ids["worker1"])
    assert row["project_count"] == 0
    assert row["planned_hours"] == 0, "A deleted project's assignment cannot still consume capacity"
    assert row["entry_count"] == 0


def test_people_summary_does_not_bypass_peer_unavailability_privacy(client, pm_headers, worker_headers):
    from app.db import SessionLocal
    ids = _ids()
    with SessionLocal() as db:
        _work(db, ids)
    _leave(client, pm_headers, ids["worker2"])
    direct = client.get(f"/api/users/{ids['worker2']}/unavailability", headers=worker_headers)
    assert direct.status_code == 403
    summary = client.get("/api/dashboard/people-summary", headers=worker_headers)
    assert summary.status_code == 200, summary.text
    assert "私人医疗说明不可向同事公开" not in summary.text
    assert "私人病假" not in summary.text


def test_assignment_check_does_not_expose_unrelated_private_leave(client, pm_headers, tech_headers):
    ids = _ids()
    _leave(client, pm_headers, ids["worker2"])
    direct = client.get(f"/api/users/{ids['worker2']}/unavailability", headers=tech_headers)
    assert direct.status_code == 403
    response = client.get("/api/schedule/assignment-check", headers=tech_headers, params={
        "user_id": ids["worker2"], "work_date": date.today().isoformat(),
    })
    assert response.status_code in (200, 403)
    assert "私人医疗说明不可向同事公开" not in response.text
    assert "私人病假" not in response.text


def test_interval_partial_updates_revalidate_against_fresh_locked_row(client, pm_headers):
    from app.db import SessionLocal
    from app.models import User, UserUnavailability
    from app.routers.availability import update_unavailability, UnavailabilityUpdate
    ids = _ids()
    uid = ids["worker1"]
    rid = _leave(client, pm_headers, uid, start="2026-10-01", end="2026-10-10")
    # Both requests have already read [1, 10]. Their independent edits are each
    # locally valid, but combining them without a locked reread creates [8, 3].
    with SessionLocal() as first, SessionLocal() as second:
        old_first = first.get(UserUnavailability, rid)
        old_second = second.get(UserUnavailability, rid)
        assert old_first.start_date == old_second.start_date == date(2026, 10, 1)
        update_unavailability(uid, rid, UnavailabilityUpdate(start_date=date(2026, 10, 8)),
                              first.get(User, ids["pm"]), first)
        try:
            update_unavailability(uid, rid, UnavailabilityUpdate(end_date=date(2026, 10, 3)),
                                  second.get(User, ids["pm"]), second)
        except HTTPException as exc:
            assert exc.status_code in (400, 409)
            second.rollback()
    with SessionLocal() as check:
        saved = check.get(UserUnavailability, rid)
        assert saved.start_date <= saved.end_date, "Two accepted partial updates created an impossible interval"
        assert saved.start_date == date(2026, 10, 8)
        assert saved.end_date == date(2026, 10, 10)


def test_people_summary_counts_conflicts_later_this_week(client, pm_headers, monkeypatch):
    from app.db import SessionLocal
    from app.routers import dashboard
    class Monday(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 5)
    monkeypatch.setattr(dashboard, "date", Monday)
    ids = _ids()
    friday = date(2026, 10, 9)
    with SessionLocal() as db:
        _work(db, ids, name="周五项目甲", day=friday)
        _work(db, ids, name="周五项目乙", day=friday)
    response = client.get("/api/dashboard/people-summary", headers=pm_headers)
    assert response.status_code == 200, response.text
    row = next(p for p in response.json()["people"] if p["id"] == ids["worker1"])
    assert row["entry_count"] == 2
    assert row["has_conflict"] is True, "This-week conflicts must include planned work after today"
    assert row["conflict_days"] == 1
    assert row["conflict_details"][0]["date"] == friday.isoformat()


def test_people_summary_excludes_inactive_members_consistently(client, pm_headers, admin_headers):
    from app.db import SessionLocal
    from app.models import User
    ids = _ids()
    with SessionLocal() as db:
        _work(db, ids)
        db.get(User, ids["worker2"]).is_active = False
        db.commit()
    pm_result = client.get("/api/dashboard/people-summary", headers=pm_headers)
    admin_result = client.get("/api/dashboard/people-summary", headers=admin_headers)
    assert pm_result.status_code == admin_result.status_code == 200
    assert ids["worker2"] not in {p["id"] for p in admin_result.json()["people"]}
    assert ids["worker2"] not in {p["id"] for p in pm_result.json()["people"]}, "Disabled account is still counted as active capacity for PM"


@pytest.mark.parametrize("members_present", [True, False])
def test_schedule_preview_reports_only_conflicts_involving_its_new_plan(client, pm_headers, members_present):
    from app.db import SessionLocal
    ids = _ids()
    today = date.today()
    with SessionLocal() as db:
        pid = _work(db, ids, name="正在预览项目", day=today,
                    members=[ids["worker1"]] if members_present else [])
        _work(db, ids, name="无关冲突项目甲", day=today + timedelta(days=1))
        _work(db, ids, name="无关冲突项目乙", day=today + timedelta(days=1))
    response = client.get(f"/api/projects/{pid}/schedule/preview", headers=pm_headers)
    assert response.status_code == 200, response.text
    assert response.json()["conflicts"] == [], "The current one-day plan is not involved in tomorrow's unrelated conflict"


def test_schedule_preview_checks_actual_overflow_dates_for_conflicts(client, pm_headers):
    from app.db import SessionLocal
    from app.models import Project, Task
    ids = _ids()
    today = date.today()
    tomorrow = today + timedelta(days=1)
    with SessionLocal() as db:
        pid = _work(db, ids, name="溢出预览项目", day=today, members=[ids["worker1"]])
        db.get(Project, pid).end_date = today
        db.query(Task).filter(Task.project_id == pid).one().target_quantity = 2
        db.commit()
        _work(db, ids, name="明日既有项目", day=tomorrow)
    response = client.get(f"/api/projects/{pid}/schedule/preview", headers=pm_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["end_date"] == tomorrow.isoformat()
    assert any(c["date"] == tomorrow.isoformat() for c in body["conflicts"]), "Overflow warning must not hide a real staffing conflict on the overflow date"


def test_overlapping_unavailability_keeps_remaining_period_after_one_cancel(client, pm_headers):
    ids = _ids()
    uid = ids["worker1"]
    first = _leave(client, pm_headers, uid)
    second = _leave(client, pm_headers, uid)
    params = {"user_id": uid, "work_date": date.today().isoformat()}
    assert client.delete(f"/api/users/{uid}/unavailability/{first}", headers=pm_headers).status_code == 200
    assert client.get("/api/schedule/assignment-check", params=params, headers=pm_headers).json()["is_available"] is False
    assert client.delete(f"/api/users/{uid}/unavailability/{second}", headers=pm_headers).status_code == 200
    assert client.get("/api/schedule/assignment-check", params=params, headers=pm_headers).json()["is_available"] is True


def test_conflict_detector_empty_people_and_required_project_remain_scoped(client, pm_headers):
    from app.db import SessionLocal
    from app.models import User
    from app.services.availability import detect_cross_project_conflicts
    ids = _ids()
    day = date.today()
    with SessionLocal() as db:
        left = _work(db, ids, name="确有冲突甲", day=day)
        _work(db, ids, name="确有冲突乙", day=day)
        other = _work(db, ids, name="不参与冲突的项目", day=day + timedelta(days=1))
        viewer = db.get(User, ids["pm"])
        assert detect_cross_project_conflicts(db, viewer, day, day, []) == {}
        assert detect_cross_project_conflicts(db, viewer, day, day, required_project_id=other) == {}
        assert detect_cross_project_conflicts(db, viewer, day, day, required_project_id="invisible-or-missing") == {}
        assert detect_cross_project_conflicts(db, viewer, day, day, required_project_id=left)[ids["worker1"]][day.isoformat()]["project_count"] == 2


def test_reschedule_preview_checks_new_dates_after_original_deadline_and_rolls_back(client, pm_headers):
    from app.db import SessionLocal
    from app.models import Project, ScheduleEntry
    ids = _ids()
    today = date.today()
    yesterday = today - timedelta(days=1)
    with SessionLocal() as db:
        pid = _work(db, ids, name="已逾期重排项目", day=yesterday, members=[ids["worker1"]])
        db.get(Project, pid).end_date = yesterday
        db.commit()
        _work(db, ids, name="今日既有项目", day=today)
        before = [(e.id, e.work_date, e.assignee_id, e.planned_quantity) for e in db.query(ScheduleEntry).filter_by(project_id=pid).all()]
    response = client.get(f"/api/projects/{pid}/schedule/reschedule-preview", params={"start_date": today.isoformat()}, headers=pm_headers)
    assert response.status_code == 200, response.text
    assert response.json()["entries"] == 1
    assert any(c["date"] == today.isoformat() for c in response.json()["conflicts"])
    with SessionLocal() as db:
        after = [(e.id, e.work_date, e.assignee_id, e.planned_quantity) for e in db.query(ScheduleEntry).filter_by(project_id=pid).all()]
        assert after == before


def test_preview_keeps_other_projects_private_and_rolls_back_generated_rows(client, pm_headers):
    from app.db import SessionLocal
    from app.models import Project, ProjectMember, ScheduleEntry
    ids = _ids()
    today = date.today()
    with SessionLocal() as db:
        pid = _work(db, ids, name="我的预览", day=today, members=[ids["worker1"]])
        hidden = _work(db, ids, name="不可见项目不得泄露", day=today)
        db.query(ProjectMember).filter_by(project_id=hidden, user_id=ids["pm"]).delete()
        db.get(Project, hidden).manager = ids["admin"]
        db.commit()
        before = [(e.id, e.work_date, e.assignee_id, e.planned_quantity) for e in db.query(ScheduleEntry).filter_by(project_id=pid).all()]
    response = client.get(f"/api/projects/{pid}/schedule/preview", headers=pm_headers)
    assert response.status_code == 200, response.text
    assert response.json()["conflicts"] == []
    assert "不可见项目不得泄露" not in response.text
    with SessionLocal() as db:
        after = [(e.id, e.work_date, e.assignee_id, e.planned_quantity) for e in db.query(ScheduleEntry).filter_by(project_id=pid).all()]
        assert after == before


def test_conflict_and_scheduler_load_skip_deleted_and_cancelled_rows(client, pm_headers):
    from app.db import SessionLocal
    from app.models import User, ScheduleEntry
    from app.services.availability import detect_cross_project_conflicts
    from app.services.scheduler import _db_day_load
    ids = _ids()
    with SessionLocal() as db:
        _work(db, ids, name="正式工作")
        _work(db, ids, name="已删除工作", deleted=True)
        cancelled_id = _work(db, ids, name="已取消工作")
        db.query(ScheduleEntry).filter(ScheduleEntry.project_id == cancelled_id).one().status = "skipped"
        db.commit()
        viewer = db.get(User, ids["pm"])
        assert _db_day_load(db, viewer, ids["worker1"], date.today()) == 8
        assert detect_cross_project_conflicts(db, viewer, date.today(), date.today(), [ids["worker1"]]) == {}
