"""Per-real-vehicle inspection seam shared by generation, planning and matrix gates.

Definitions are immutable project snapshots, never inspection results. Callers
serialize writes on the Project before invoking this module; no function commits.
Legacy task-level rows remain facts and do not pretend to verify a named unit.
"""
from fastapi import HTTPException
from sqlalchemy import or_
from app.models import (Task, CheckItem, VehicleUnit, Vehicle, VehicleStep,
                        ProjectVehicleStep, VehicleCheckDefinition, User, Module, Phase)
from app.services.manual_completion import covers


def _vehicle_tasks(db,project_id):
    # SessionLocal disables autoflush. Preserve caller-owned scope/target edits
    # before the locked fresh read instead of overwriting them from old rows.
    db.flush()
    from app.services.work_items import tasks_query
    return tasks_query(db,[project_id]).filter(Task.quantity_type=='per_vehicle').populate_existing().all()



def validate_step(db, task, key):
    if key is not None and not isinstance(key,str):
        raise HTTPException(400, '车辆环节标识须为字符串')
    key = (key or '').strip() or None
    if key is None:
        return None
    if task.quantity_type != 'per_vehicle':
        raise HTTPException(400, '只有按车辆的工作可以关联车辆环节')
    from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES
    from app.services.work_items import phase_of
    phase=phase_of(db,task)
    if phase is not None and phase.name in REMINDER_ONLY_PHASE_NAMES:
        raise HTTPException(400,'准备提醒不作为车辆实施环节，请在实施工作中明确关联')
    if task.project_id:
        exists = db.query(ProjectVehicleStep.id).filter_by(project_id=task.project_id, key=key).first()
    else:
        from app.services.vehicle_progress import DEFAULT_STEPS
        tid = task.template_id or 'default'
        rows = db.query(VehicleStep).filter_by(template_id=tid).all()
        exists = any(row.key == key for row in rows) if rows else key in dict(DEFAULT_STEPS)
    if not exists:
        raise HTTPException(400, '车辆环节不属于当前项目或模板')
    return key


def bind_step(db, task, key):
    """Only planning callers may bind; qualified facts can never be rebound."""
    key = validate_step(db, task, key)
    if key == task.vehicle_step_key:
        return
    rows = db.query(CheckItem).filter_by(task_id=task.id).all()
    if task.vehicle_step_key and any(c.is_done or c.failed or not c.is_applicable or c.done_at for c in rows):
        raise HTTPException(400, '已有检查事实的工作不能改绑环节；请保留原来源并新增工作定义')
    # An unbound legacy result may be explicitly linked once, but its original
    # task-level identity/state is retained. It never becomes a per-unit pass.
    for row in rows:
        if row.vehicle_unit_id:
            if row.is_done or row.failed or not row.is_applicable or row.done_at:
                raise HTTPException(400, '已有逐车检查事实，不能改绑环节')
            row.vehicle_step_key = key
    task.vehicle_step_key = key


def _applies(db, task, unit):
    types = task.applicable_vehicle_types or []
    if not types:
        return True
    vehicle = db.get(Vehicle, unit.vehicle_id) if unit.vehicle_id else None
    # Unknown type is not evidence of exclusion; keep its safety obligations.
    return vehicle is None or vehicle.vehicle_type in types


def snapshot_definitions(db, task, source_checks):
    """Freeze definitions only. A passed source never grants new qualification."""
    if task.quantity_type != 'per_vehicle':
        return []
    existing = {r.source_check_id: r for r in db.query(VehicleCheckDefinition).filter_by(task_id=task.id)}
    for check in source_checks:
        if check.id not in existing:
            definition = VehicleCheckDefinition(project_id=task.project_id, task_id=task.id,
                source_check_id=check.id, source_version=check.version or 0, version=1,
                name=check.name, description=check.description,
                is_safety_critical=check.is_safety_critical, is_required=check.is_required,
                sort_order=check.sort_order)
            db.add(definition)
            existing[check.id] = definition
    db.flush()
    return list(existing.values())


def generate_for_units(db, project_id, units, task=None):
    """Idempotently create pending rows, only for caller-selected real units.

    New-unit and new-definition callers select automatically. Existing legacy
    units are selected only by an explicit, audited planning action.
    """
    tasks = _vehicle_tasks(db,project_id)
    if task is not None:tasks=[work for work in tasks if work.id==task.id]
    created = []
    for work in tasks:
        definitions = db.query(VehicleCheckDefinition).filter_by(task_id=work.id).order_by(VehicleCheckDefinition.sort_order).all()
        existing = {(r.vehicle_unit_id, r.vehicle_check_definition_id) for r in db.query(CheckItem).filter_by(task_id=work.id) if r.vehicle_unit_id}
        for unit in units:
            if unit.project_id != project_id or not _applies(db, work, unit):
                continue
            for definition in definitions:
                if (unit.id, definition.id) in existing:
                    continue
                row = CheckItem(project_id=project_id, task_id=work.id, vehicle_unit_id=unit.id,
                    vehicle_step_key=work.vehicle_step_key, vehicle_check_definition_id=definition.id,
                    definition_version=definition.version, name=definition.name, description=definition.description,
                    is_required=definition.is_required, is_safety_critical=definition.is_safety_critical,
                    sort_order=definition.sort_order, is_done=False, failed=False, is_applicable=True,
                    version=0, done_by=None, done_at=None)
                db.add(row)
                created.append(row)
                existing.add((unit.id, definition.id))
    db.flush()
    return created


def _definition_error(db, check):
    if not check.vehicle_unit_id:
        return None
    definition=db.get(VehicleCheckDefinition,check.vehicle_check_definition_id,populate_existing=True) if check.vehicle_check_definition_id else None
    if definition is None or definition.task_id!=check.task_id or definition.project_id!=check.project_id or definition.version!=check.definition_version:
        return '检查定义来源版本待核对，原结果不能授予新定义资格'
    fields=('name','description','is_required','is_safety_critical')
    if any((getattr(definition,k) or '')!=(getattr(check,k) or '') for k in fields):
        return '检查定义内容已变化，请保留原检查并生成明确版本的复核'
    return None


def ensure_check_mapping(db,check,task):
    if not check.vehicle_step_key or check.vehicle_step_key!=task.vehicle_step_key:
        raise HTTPException(400,'逐车检查尚未关联明确环节，请负责人核对工作关联')
    reason=_definition_error(db,check)
    if reason:raise HTTPException(400,reason)


def _reason(task, check):
    if check.is_safety_critical:
        if not check.is_applicable or not check.is_done or check.failed:
            return '安全关键检查须真实通过，不能不适用或直接完成覆盖'
        return None
    if check.failed and check.is_applicable:
        return None if covers(task, check) else '检查不通过，需处理或由负责人对当前失败版本明确说明'
    if check.is_required and check.is_applicable and not check.is_done:
        return '必需检查尚未完成，直接完成不能覆盖待检项'
    return None


def checks_for_unit(db, project_id, unit_id, step_key=None):
    unit = db.get(VehicleUnit, unit_id)
    if unit is None or unit.project_id != project_id:
        raise HTTPException(404, '车辆不属于当前项目')
    tasks = {t.id: t for t in _vehicle_tasks(db,project_id) if _applies(db, t, unit)}
    rows = db.query(CheckItem).filter(CheckItem.task_id.in_(tasks),
        or_(CheckItem.project_id == project_id, CheckItem.project_id.is_(None)),
        or_(CheckItem.vehicle_unit_id == unit.id, CheckItem.vehicle_unit_id.is_(None))).populate_existing().order_by(CheckItem.sort_order, CheckItem.id).all() if tasks else []
    result = []
    for row in rows:
        task = tasks[row.task_id]
        key = row.vehicle_step_key if row.vehicle_unit_id else task.vehicle_step_key
        if step_key and key and key != step_key:
            continue
        reason = _definition_error(db,row) or _reason(task, row)
        if not key and (row.is_required or row.is_safety_critical or row.failed):
            reason = '按车工作尚未关联本项目车辆环节，请负责人明确关联'
        result.append({'id': row.id, 'task_id': task.id, 'task_name': task.name, 'task_version': task.version or 0,
            'vehicle_unit_id': row.vehicle_unit_id, 'vehicle_step_key': key,
            'scope': 'vehicle' if row.vehicle_unit_id else 'legacy_task',
            'name': row.name, 'description': row.description, 'is_required': row.is_required,
            'is_safety_critical': row.is_safety_critical, 'is_applicable': row.is_applicable,
            'not_applicable_reason': row.not_applicable_reason, 'is_done': row.is_done,
            'failed': row.failed, 'failed_reason': row.failed_reason, 'done_by': row.done_by,
            'done_at': row.done_at.isoformat()+'Z' if row.done_at else None, 'done_by_name': (db.get(User,row.done_by).display_name if db.get(User,row.done_by) else '原操作人未记录') if row.done_by else '', 'version': row.version or 0,
            'source_definition_id': row.vehicle_check_definition_id, 'definition_version': row.definition_version,
            'blocker': reason})
    return result


def completion_blockers(db, project_id, cells):
    """Re-read under the same Project lock; all blockers before any cell write."""
    blockers = []
    for cell in cells:
        unit=db.get(VehicleUnit,cell.vehicle_unit_id)
        label=(unit.fleet_no or unit.asset_code) if unit else cell.vehicle_unit_id
        rows = checks_for_unit(db, project_id, cell.vehicle_unit_id, cell.step_key)
        for row in rows:
            if row['blocker']:
                blockers.append({'vehicle_unit_id': cell.vehicle_unit_id, 'vehicle_label':label, 'step_key': cell.step_key,
                    'check_id': row['id'], 'check_version': row['version'], 'task_id': row['task_id'],
                    'name': row['name'], 'reason': row['blocker'], 'scope': row['scope']})
    return blockers


def definition_data(db, task):
    """Portable requirements, never one duplicate definition per inspected car."""
    definitions = db.query(VehicleCheckDefinition).filter_by(task_id=task.id).order_by(VehicleCheckDefinition.sort_order, VehicleCheckDefinition.id).all()
    result = [{'source_check_id': d.source_check_id, 'source_version': d.source_version,
               'name': d.name, 'description': d.description or '', 'is_required': d.is_required,
               'is_safety_critical': d.is_safety_critical, 'sort_order': d.sort_order} for d in definitions]
    sources = {d.source_check_id for d in definitions}
    for check in db.query(CheckItem).filter_by(task_id=task.id, vehicle_unit_id=None).filter(or_(CheckItem.project_id==task.project_id,CheckItem.project_id.is_(None))).order_by(CheckItem.sort_order, CheckItem.id):
        if check.id not in sources:
            result.append({'source_check_id': check.id, 'source_version': check.version or 0,
                'name': check.name, 'description': check.description or '', 'is_required': check.is_required,
                'is_safety_critical': check.is_safety_critical, 'sort_order': check.sort_order})
    return result


def import_definitions(db, task, values):
    from types import SimpleNamespace
    from uuid import uuid4
    source_ids=set()
    for value in values:
        source_id=value.get('source_check_id')
        version=value.get('source_version',0)
        if source_id is not None and (not isinstance(source_id,str) or not source_id or len(source_id)>36):
            raise HTTPException(400,'检查定义来源标识无效')
        if source_id is not None:
            if source_id in source_ids:raise HTTPException(400,'检查定义来源标识重复')
            source_ids.add(source_id)
        if isinstance(version,bool) or not isinstance(version,int) or not 0<=version<=2147483647:
            raise HTTPException(400,'检查定义来源版本无效')
    source = [SimpleNamespace(id=str(value.get('source_check_id') or uuid4()),
        version=int(value.get('source_version') or 0), name=value.get('name') or '检查项',
        description='\n'.join(filter(None,[value.get('description') or '',
            f"验收标准：{value['acceptance_standard']}" if value.get('acceptance_standard') else '',
            f"证据要求：{value['evidence_required']}" if value.get('evidence_required') else ''])), is_required=bool(value.get('is_required', True)),
        is_safety_critical=bool(value.get('is_safety_critical', False)), sort_order=index)
        for index,value in enumerate(values)]
    return snapshot_definitions(db, task, source)


def vehicle_label(db, check):
    if not check.vehicle_unit_id:
        return '任务级检查（未逐车核验）'
    unit=db.get(VehicleUnit,check.vehicle_unit_id)
    return (unit.fleet_no or unit.asset_code) if unit else '车辆来源待核对'


def reconcile_vehicle_type(db, project_id, units, previous_type):
    """Only newly-applicable scope gains pending checks on a fleet type change.

    Always-applicable legacy NULL checks are not retroactively expanded. Deleting
    a known type leaves a real unit's type unknown, which cannot prove exemption.
    """
    if previous_type is None:
        return []
    created=[]
    for task in _vehicle_tasks(db,project_id):
        types=task.applicable_vehicle_types or []
        if not types or previous_type in types:
            continue
        selected=[unit for unit in units if _applies(db,task,unit)]
        if selected:created.extend(generate_for_units(db,project_id,selected,task))
    return created


def check_block_reason(db, task, check):
    """Shared current qualification, including exact source-definition versions."""
    return _definition_error(db, check) or _reason(task, check)
