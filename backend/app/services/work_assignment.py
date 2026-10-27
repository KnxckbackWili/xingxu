"""Repair work definitions link real issue records to explicit weekly intent."""
from fastapi import HTTPException
from app.models import Task, Phase
from app.services.permissions import C_PLAN, authorize_project
from app.services.system_permissions import has_permission
from app.services.change_log import log_change


def validate_positive_task_targets(tasks):
    raise HTTPException(410, '按日目标数量已退休，请使用工作项与周计划')


def create_assignment(*args, **kwargs):
    raise HTTPException(410, '按天安排已退休，请使用明确的周计划')


def create_repair_work(db, project, actor, event, unit, notes):
    if event.is_closed:
        raise HTTPException(400, '车辆问题已关闭，请先根据实际情况重新打开问题再安排处理')
    task = db.query(Task).filter_by(project_id=project.id, source_vehicle_event_id=event.id).first()
    if task:
        if task.manually_completed:
            raise HTTPException(400, '该维修工作已完成，请先按真实情况重新打开工作')
        return task, False
    if not has_permission(actor, 'project.manage_plan', default=True):
        raise HTTPException(403, '此故障尚无工作项，需要工作计划维护权限明确建立')
    authorize_project(actor, project, C_PLAN)
    phase = db.query(Phase).filter_by(project_id=project.id, name='现场追加工作').first()
    if phase is None:
        phase = Phase(project_id=project.id, name='现场追加工作', sort_order=90, color='#c07130')
        db.add(phase); db.flush()
    task = Task(project_id=project.id, phase_id=phase.id, module_id=None,
        group_label='车辆维修', name=f'维修 {unit.asset_code} · {event.title}'[:200], description=notes,
        quantity_type='fixed', target_quantity=None, unit='项', source_vehicle_event_id=event.id)
    db.add(task); db.flush()
    log_change(db, project.id, 'task', task.id, 'create', actor.id, '从真实车辆问题建立维修工作项；未推定处理人或完成事实')
    return task, True
