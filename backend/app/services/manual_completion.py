"""Bind an ordinary failed-check override to the exact evidence reviewed."""
from app.models import CheckItem


def failed_checks(db, task_id):
    return db.query(CheckItem).filter(CheckItem.task_id == task_id, CheckItem.is_applicable.is_(True),
        CheckItem.failed.is_(True), CheckItem.is_safety_critical.is_not(True)).order_by(CheckItem.sort_order, CheckItem.id).all()


def snapshot(checks):
    return [{'check_id': row.id, 'version': row.version or 0, 'name': row.name,
             'failed_reason': row.failed_reason or ''} for row in checks]


def covers(task, check):
    if check.task_id != task.id or not check.failed or not check.is_applicable or check.is_safety_critical:
        return False
    if not task.manually_completed or not (task.manual_completed_reason or '').strip():
        return False
    return any(isinstance(item, dict) and item.get('check_id') == check.id
        and item.get('version') == (check.version or 0)
        and item.get('failed_reason', '') == (check.failed_reason or '')
        for item in task.manual_check_overrides or [])
