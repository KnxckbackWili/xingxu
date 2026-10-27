"""Bind an ordinary failed-check override to the exact evidence reviewed."""
from app.models import CheckItem, Task, User


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


def review_overrides(db, project_id):
    tasks = db.query(Task).filter_by(project_id=project_id, manually_completed=True).order_by(Task.sort_order, Task.id).all()
    identities = {task.manual_completed_by for task in tasks if task.manual_completed_by}
    names = {row.id: row.display_name for row in db.query(User).filter(User.id.in_(identities))}
    checks = {row.id: row for row in db.query(CheckItem).filter(CheckItem.task_id.in_([task.id for task in tasks]))}
    return [{'task_id': task.id, 'task_name': task.name, 'reason': task.manual_completed_reason or '',
        'actor_name': names.get(task.manual_completed_by, '原操作人未记录'),
        'recorded_at': task.manual_completed_at.isoformat() if task.manual_completed_at else None,
        'checks': [{**item, 'still_current': item.get('check_id') in checks and covers(task, checks[item['check_id']])}
                   for item in task.manual_check_overrides or [] if isinstance(item, dict)],
        'url': f'/pm/projects/{project_id}/plan?task={task.id}'}
        for task in tasks if task.manual_check_overrides]
