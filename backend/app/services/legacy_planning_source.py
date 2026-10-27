"""Read-only original planning facts; no effort learning or policy reconstruction."""
from app.models import ProjectSchedulePolicy, TaskDurationOverride, ChangeLog
from app.services.project_retention import _row


def snapshot(db, project_id):
    return {'read_only':True, 'meaning':'旧按日倍率、人工工期和原调整审计仅作来源，不参与当前周计划',
        'project_schedule_policies':[_row(row) for row in db.query(ProjectSchedulePolicy).filter_by(project_id=project_id).order_by(ProjectSchedulePolicy.project_id)],
        'task_duration_overrides':[_row(row) for row in db.query(TaskDurationOverride).filter_by(project_id=project_id).order_by(TaskDurationOverride.task_id)],
        'schedule_range_audits':[_row(row) for row in db.query(ChangeLog).filter_by(project_id=project_id,entity_type='task',action='schedule_range').order_by(ChangeLog.id)]}
