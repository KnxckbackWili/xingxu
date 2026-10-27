"""Effort statistics: derive actual per-unit hours from work reports.

Each DailyProgress row = one person working on one task for one day (人天).
So:
    total_person_days  = number of report rows for the task
    actual_hours/unit  = total_person_days * 8 / completed_quantity

This is a read-only historical source. It never feeds current weekly plans.
"""

from datetime import date, timedelta
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Task, DailyProgress, Project

WORK_HOURS_PER_DAY = 8


def task_effort_stats(db: Session, task: Task, days: int = 180):
    """Actual effort for one task (its own project): person-days & hours/unit."""
    q = db.query(
        func.coalesce(func.sum(DailyProgress.completed_quantity), 0),
        func.count(DailyProgress.id),
    ).filter(DailyProgress.task_id == task.id)
    if days:
        q = q.filter(DailyProgress.work_date >= date.today() - timedelta(days=days))
    total_qty, person_days = q.one()
    total_qty = round(total_qty or 0, 2)
    hours_per_unit = None
    if total_qty and total_qty > 0:
        hours_per_unit = round(person_days * WORK_HOURS_PER_DAY / total_qty, 2)
    return {
        "task_id": task.id,
        "task_name": task.name,
        "completed_quantity": total_qty,
        "person_days": person_days,
        "hours_per_unit": hours_per_unit,
        "source": "stats",
    }
