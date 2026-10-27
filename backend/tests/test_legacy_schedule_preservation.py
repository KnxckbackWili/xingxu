"""旧日程来源保全与退役行为边界。"""

from datetime import date
import pytest
from app.models import ScheduleEntry
from app.services.scheduler import generate_schedule
from app.services.status_flow import advance_project_status, regress_project_status
from tests.test_scheduler_integrity import plan, entries, report


@pytest.mark.parametrize('locked', [False, True])
def test_cancelled_rows_preserved_without_reserving_unperformed_quantity(plan, locked):
    db, project, task, _ = plan
    cancelled = entries(db, task)[0]
    cancelled.status = 'skipped'
    cancelled.is_locked = locked
    cancelled.work_date = date(2026, 12, 1)
    db.flush()
    generate_schedule(db, project)
    actual = entries(db, task)
    assert cancelled.id in {entry.id for entry in actual}
    live = [entry for entry in actual if entry.status != 'skipped']
    assert sum(entry.planned_quantity for entry in live) == task.target_quantity
    assert live[0].work_date == project.start_date


def test_cancelled_reported_row_only_reserves_actual_work(plan):
    db, project, task, _ = plan
    cancelled = entries(db, task)[0]
    cancelled.status = 'skipped'
    report(db, project, task, cancelled, quantity=1)
    db.flush()
    generate_schedule(db, project)
    assert sum(entry.planned_quantity for entry in entries(db, task) if entry.status != 'skipped') == 3


def test_done_draft_row_survives_regeneration(plan):
    db, project, task, _ = plan
    finished = entries(db, task)[0]
    finished.status = 'done'
    db.flush()
    generate_schedule(db, project)
    assert finished.id in {entry.id for entry in entries(db, task)}
    assert sum(entry.planned_quantity for entry in entries(db, task)) == task.target_quantity


def test_long_single_unit_split_policy_remains_unchanged(plan):
    db, project, task, _ = plan
    task.target_quantity = 1
    task.standard_hours = 24
    db.flush()
    generate_schedule(db, project)
    planned = entries(db, task)
    assert len(planned) == 3
    assert sum(entry.planned_quantity for entry in planned) == pytest.approx(1)
    # Daily per-piece distribution is a product decision, not changed by this review.
    assert [entry.planned_quantity for entry in planned] == [1, 0, 0]


@pytest.mark.parametrize('initial', ['planning', 'ready'])
def test_only_cancelled_confirmations_do_not_establish_released_work(plan, initial):
    db, project, task, following = plan
    for entry in db.query(ScheduleEntry).filter_by(project_id=project.id).all():
        entry.is_confirmed = True
        entry.status = 'skipped'
    project.status = initial
    db.flush()
    if initial == 'planning':
        assert advance_project_status(db, project) is None
    else:
        assert regress_project_status(db, project) == 'planning'
    assert project.status == 'planning'


def test_cancelled_quantity_excluded_from_current_plan_timeline(plan):
    from app.services.progress import plan_vs_actual_timeline
    db, project, task, _ = plan
    cancelled = entries(db, task)[0]
    cancelled.status = 'skipped'
    db.flush()
    generate_schedule(db, project)
    timeline = plan_vs_actual_timeline(db, project.id, project.start_date, project.end_date)
    assert timeline[-1]['planned'] == 6
