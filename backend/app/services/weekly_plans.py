"""Weekly planning owns plans; matrix/work services own actual qualification.

Every mutation takes Project, policy User anchor, then stable record locks.
Functions never commit, assign people automatically, or replay daily quantities.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, or_

from app.models import (WeeklyPlanCell, Project, Task, Phase, User, Vehicle, VehicleUnit,
                        VehicleProgress, VehicleProgressMigration, ProjectVehicleStep,
                        UserUnavailability)
from app.services.permissions import C_SCHEDULE, authorize_project, project_capabilities
from app.services.system_permissions import has_permission
from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES
from app.services.record_lock import lock_record, lock_writable_project
from app.services.optimistic import bump_version
from app.services.change_log import log_change
from app.services import work_items as work
from app.time_utils import utcnow


def monday(day):
    begin = day - timedelta(days=day.weekday())
    try:
        begin + timedelta(days=6)
    except OverflowError:
        raise HTTPException(400, '所选日期无法组成完整周，请选择有效日期范围') from None
    return begin


def window_end(start, weeks):
    try:
        return monday(start) + timedelta(weeks=weeks, days=-1)
    except OverflowError:
        raise HTTPException(400, '周计划查询超出有效日期范围') from None


def local_today(project):
    return datetime.now(ZoneInfo(project.timezone or 'Asia/Shanghai')).date()


def select_cells(db, project_ids, week_start, weeks, *, published_only=True, user=None):
    """Bounded read seam; caller supplies already-authorized project IDs."""
    if not project_ids:
        return []
    start = monday(week_start)
    rows = db.query(WeeklyPlanCell).filter(
        WeeklyPlanCell.project_id.in_(project_ids), WeeklyPlanCell.week_start >= start,
        WeeklyPlanCell.week_start <= window_end(start, weeks),
        WeeklyPlanCell.is_cancelled.is_(False))
    if published_only:
        rows = rows.filter(WeeklyPlanCell.published.is_(True))
    result = rows.order_by(WeeklyPlanCell.week_start, WeeklyPlanCell.task_id, WeeklyPlanCell.id).all()
    return [cell for cell in result if user is None or user.id in (cell.assignee_ids or [])]


def select_unassigned_cells(db, project_ids, week_start, weeks):
    return [cell for cell in select_cells(db, project_ids, week_start, weeks) if not cell.assignee_ids]


def member_ids(project):
    return set(project.members or []) | {v for v in (project.manager, project.technical_manager) if v}


def can_edit(project, actor):
    return (project.status in ACTIVE_PROJECT_STATUSES and
            has_permission(actor, 'project.manage_schedule', default=True) and
            C_SCHEDULE in project_capabilities(actor, project))


def can_claim(project, actor):
    return project.status in ACTIVE_PROJECT_STATUSES and actor.id in member_ids(project) and has_permission(actor, 'worker.report', default=True)


def lock_authority(db, project, actor, *, assignees=(), claim=False):
    old_token = actor.token_version or 0
    project = lock_writable_project(db, project, actor)
    anchor = db.query(User).filter_by(username='admin').first() or db.query(User).order_by(User.id).first()
    if anchor:
        lock_record(db, anchor, conflict_detail='人员授权正在变化，请刷新后重试')
    identities = sorted(({actor.id} | set(assignees)) - ({anchor.id} if anchor else set()))
    if identities:
        db.execute(select(User.id).where(User.id.in_(identities)).order_by(User.id).with_for_update()).all()
    db.refresh(actor)
    if not actor.is_active or (actor.token_version or 0) != old_token:
        raise HTTPException(401, '账号或会话已变化，请重新登录')
    if claim:
        if not can_claim(project, actor):
            raise HTTPException(403, '仅有填报权限的当前项目成员可明确认领')
    else:
        if not has_permission(actor, 'project.manage_schedule', default=True):
            raise HTTPException(403, '周计划维护权限已变化')
        authorize_project(actor, project, C_SCHEDULE)
        if project.status not in ACTIVE_PROJECT_STATUSES:
            raise HTTPException(400, '项目暂停或结束后不能维护周计划，请先明确恢复状态')
    return project


def task_for(db, project, task_id):
    task = db.get(Task, task_id, populate_existing=True)
    if task is None or task.project_id != project.id:
        raise HTTPException(404, '工作项不存在')
    phase = work.phase_of(db, task)
    if phase is None or phase.name == '项目准备':
        raise HTTPException(400, '请选择真实实施工作，历史准备来源不进入周计划')
    return task


def normalize_scope(db, project, task, value):
    value = value or {}
    ids = sorted(set(value.get('vehicle_unit_ids') or []))
    kind = (value.get('vehicle_type') or '').strip() or None
    label = (value.get('label') or '').strip()
    if not work.is_vehicle(task) and (ids or kind):
        raise HTTPException(400, '非车辆工作不接受选车范围')
    if ids and kind:
        raise HTTPException(400, '请选择车型或明确车号批次中的一种范围')
    if ids:
        actual = db.query(VehicleUnit).filter(VehicleUnit.project_id == project.id, VehicleUnit.id.in_(ids)).all()
        if {unit.id for unit in actual} != set(ids):
            raise HTTPException(404, '所选真实车号不属于当前项目或已变化')
        if task.applicable_vehicle_types:
            types = {row.id: row.vehicle_type for row in db.query(Vehicle).filter_by(project_id=project.id)}
            if any(types.get(unit.vehicle_id) not in task.applicable_vehicle_types for unit in actual):
                raise HTTPException(400, '所选车号不在当前工作适用车型范围，车型归属未知时请先核对')
    if kind and not db.query(Vehicle.id).filter_by(project_id=project.id, vehicle_type=kind).first():
        raise HTTPException(400, '所选车型未在本项目配置，请先核对车型与数量')
    if kind and task.applicable_vehicle_types and kind not in task.applicable_vehicle_types:
        raise HTTPException(400, '所选车型不在当前工作适用范围')
    scope = {'vehicle_unit_ids': ids}
    if kind:
        scope['vehicle_type'] = kind
    if label:
        scope['label'] = label
    identity = json.dumps({'vehicle_unit_ids': ids, 'vehicle_type': kind}, sort_keys=True, separators=(',', ':'))
    return scope, 'scope:' + sha256(identity.encode()).hexdigest()[:40]


def scope_identity(cell):
    scope = cell.scope or {}
    return json.dumps({'vehicle_unit_ids': sorted(scope.get('vehicle_unit_ids') or []),
                       'vehicle_type': scope.get('vehicle_type') or None}, sort_keys=True, separators=(',', ':'))


def validate_assignees(db, project, identities):
    identities = sorted(set(identities))
    if set(identities) - member_ids(project):
        raise HTTPException(400, '周计划负责人须是当前项目成员或负责人，请先在成员设置中添加')
    rows = db.query(User).filter(User.id.in_(identities)).populate_existing().all() if identities else []
    if {row.id for row in rows if row.is_active and row.role not in ('external', 'readonly')} != set(identities):
        raise HTTPException(400, '负责人账号已停用或没有现场成员资格，请核对后重新选择')
    return identities


def _target(task, mode, count, *, legacy=False):
    if mode == 'in_progress':
        if count is not None:
            raise HTTPException(400, '进行中的安排不填写完成台数')
        return None
    if work.is_vehicle(task):
        if count is None and legacy:
            return None  # Original fractional quantity remains explicitly unreviewed.
        if isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= 2147483647:
            raise HTTPException(400, '车辆完成目标须填写正整数台数')
        if not task.vehicle_step_key:
            raise HTTPException(400, '车辆工作尚未明确关联真实进度环节，请先核对工作定义')
        return count
    if count is not None:
        raise HTTPException(400, '非车辆工作只有完成状态，不填写目标数量')
    return None


def _duplicate(db, cell):
    others = db.query(WeeklyPlanCell).filter_by(project_id=cell.project_id, task_id=cell.task_id,
        week_start=cell.week_start, is_cancelled=False).all()
    return any(other.id != cell.id and scope_identity(other) == scope_identity(cell) for other in others)


def _notify(db, project, cell, actor, people, title):
    from app.services.notify import notify
    task = db.get(Task, cell.task_id)
    for identity in sorted(set(people) - {actor.id}):
        person = db.get(User, identity)
        if person and person.is_active:
            notify(db, identity, f'{title} · {project.name}',
                   f'{cell.week_start} 起的一周：{task.name if task else "原工作"}。请核对最新周计划。',
                   ntype='schedule_confirmed', project_id=project.id, entity_id=cell.id)


def _raw(cell):
    return {'week_start': cell.week_start.isoformat(), 'scope': cell.scope, 'mode': cell.mode,
            'target_count': cell.target_count, 'assignee_ids': cell.assignee_ids,
            'intent_review_required': bool(cell.intent_review_required),
            'published': cell.published, 'is_cancelled': cell.is_cancelled,
            'notes': cell.notes, 'vehicle_step_key': cell.vehicle_step_key}


def create(db, project, actor, values, *, already_locked=False):
    if not already_locked:
        project = lock_authority(db, project, actor, assignees=values.get('assignee_ids') or [])
    task = task_for(db, project, values['task_id'])
    scope, key = normalize_scope(db, project, task, values.get('scope'))
    identities = validate_assignees(db, project, values.get('assignee_ids') or [])
    mode = values.get('mode', 'in_progress')
    count = _target(task, mode, values.get('target_count'))
    row = WeeklyPlanCell(project_id=project.id, task_id=task.id, scope=scope, scope_key=key,
        vehicle_step_key=task.vehicle_step_key, week_start=monday(values['week_start']), mode=mode,
        target_count=count, assignee_ids=identities, notes=values.get('notes') or '', published=False,
        is_cancelled=False, source_metadata=values.get('_draft_source'), created_by=actor.id, updated_by=actor.id, version=0)
    cancelled = db.query(WeeklyPlanCell.id).filter_by(project_id=project.id,task_id=task.id,scope_key=key,week_start=row.week_start,is_cancelled=True).first()
    if cancelled:
        raise HTTPException(409, '同一工作、范围和周已有已取消格子，请显示已取消计划后明确恢复')
    if _duplicate(db, row):
        raise HTTPException(409, '同一工作、选车范围和周已有计划，请直接修改现有格子')
    db.add(row); db.flush()
    log_change(db, project.id, 'weekly_plan', row.id, 'create', actor.id, '新增周计划（未发布）', None, _raw(row))
    return row


def update(db, project, actor, cell_id, values):
    identities = values.get('assignee_ids') or []
    project = lock_authority(db, project, actor, assignees=identities)
    row = db.get(WeeklyPlanCell, cell_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(404, '周计划不存在')
    lock_record(db, row, conflict_detail='周计划已被其他人更新，请刷新核对')
    bump_version(row, values['version'])
    task = task_for(db, project, row.task_id)
    old = _raw(row)
    if row.intent_review_required and {'mode', 'target_count'} & values.keys() and not values.get('confirm_intent'):
        raise HTTPException(400, '原计划量或意图仍未知；修改目标须明确确认并填写核对理由')
    if 'week_start' in values:
        row.week_start = monday(values['week_start'])
    if 'scope' in values:
        row.scope, row.scope_key = normalize_scope(db, project, task, values['scope'])
    if 'assignee_ids' in values:
        row.assignee_ids = validate_assignees(db, project, values['assignee_ids'])
    if 'notes' in values:
        row.notes = values['notes']
    mode = values.get('mode', row.mode)
    count = values.get('target_count', row.target_count)
    if mode == 'in_progress' and 'target_count' not in values:
        count = None
    row.mode = mode
    row.target_count = _target(task, mode, count, legacy=(row.source_metadata or {}).get('kind') == 't40_legacy_daily_rollup' and 'target_count' not in values and 'mode' not in values)
    if values.get('confirm_intent'):
        if 'mode' not in values or not (values.get('reason') or '').strip():
            raise HTTPException(400, '明确核对历史计划意图须选择进行中或完成目标，并填写核对理由')
        row.intent_review_required = False
    row.vehicle_step_key = task.vehicle_step_key
    if 'is_cancelled' in values and values['is_cancelled'] != row.is_cancelled:
        if not (values.get('reason') or '').strip():
            raise HTTPException(400, '取消或恢复周计划须填写理由')
        row.is_cancelled = values['is_cancelled']
    if not row.is_cancelled and ('scope' in values or 'week_start' in values or 'is_cancelled' in values) and _duplicate(db, row):
        raise HTTPException(409, '该周已有同一工作与范围的计划；原格子保持不变')
    row.updated_by = actor.id; row.updated_at = utcnow()
    if row.published and old != _raw(row):
        _notify(db, project, row, actor, set(old['assignee_ids'] or []) | set(row.assignee_ids or []), '周计划已修改')
    log_change(db, project.id, 'weekly_plan', row.id, 'update', actor.id,
               '修改周计划' + (f'；{values["reason"]}' if values.get('reason') else ''), old, _raw(row))
    db.flush()
    return row


def publish(db, project, actor, selected, *, phase_id=None):
    project = lock_authority(db, project, actor)
    identities = [value['id'] for value in selected]
    if len(set(identities)) != len(identities):
        raise HTTPException(400, '发布范围不能包含重复格子')
    rows = db.query(WeeklyPlanCell).filter(WeeklyPlanCell.project_id == project.id, WeeklyPlanCell.id.in_(identities)).order_by(WeeklyPlanCell.id).all()
    if len(rows) != len(identities):
        raise HTTPException(404, '所选周计划已变化或不属于当前项目')
    versions = {value['id']: value['version'] for value in selected}
    changed = []
    for row in rows:
        lock_record(db, row, conflict_detail='发布范围已变化，请刷新核对')
        if row.is_cancelled:
            raise HTTPException(409, '所选范围含已取消计划，请重新核对')
        task = task_for(db, project, row.task_id)
        if phase_id and work.phase_of(db, task).id != phase_id:
            raise HTTPException(409, '工作阶段归属已变化，请重新核对发布范围')
        if (row.version or 0) != versions[row.id]:
            raise HTTPException(409, '周计划版本已变化，请重新核对发布范围')
        if row.published:
            continue
        if row.intent_review_required:
            raise HTTPException(400, '历史计划量或意图仍待核对，请先明确确认本周计划再发布')
        validate_assignees(db, project, row.assignee_ids or [])
        _target(task, row.mode, row.target_count)
        if row.vehicle_step_key != task.vehicle_step_key:
            raise HTTPException(409, '车辆工作环节已变化，请先明确更新该格子')
        bump_version(row, versions[row.id])
        row.published = True; row.published_at = utcnow(); row.published_by = actor.id
        row.updated_by = actor.id; row.updated_at = utcnow()
        _notify(db, project, row, actor, row.assignee_ids or [], '周计划已发布')
        log_change(db, project.id, 'weekly_plan', row.id, 'publish', actor.id, '发布明确选定的周计划', None, _raw(row))
        changed.append(row.id)
    db.flush()
    return changed


def claim(db, project, actor, cell_id, version):
    project = lock_authority(db, project, actor, claim=True)
    row = db.get(WeeklyPlanCell, cell_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(404, '周计划不存在')
    lock_record(db, row, conflict_detail='该计划已由其他成员更新，请刷新核对')
    bump_version(row, version)
    if not row.published or row.is_cancelled or row.assignee_ids:
        raise HTTPException(409, '仅可明确认领已发布且尚无负责人的周计划')
    task_for(db, project, row.task_id)
    row.assignee_ids = [actor.id]; row.updated_by = actor.id; row.updated_at = utcnow()
    log_change(db, project.id, 'weekly_plan', row.id, 'claim', actor.id, '成员明确认领周计划', {'assignee_ids': []}, {'assignee_ids': [actor.id]})
    db.flush()
    return row


def _unit_scope(db, project, task, scope, step):
    from app.services.vehicle_progress import fleet_scope
    units, total, fleet_unknown = fleet_scope(db, project.id)
    ids = set(scope.get('vehicle_unit_ids') or [])
    kind = scope.get('vehicle_type')
    configured = db.query(Vehicle).filter_by(project_id=project.id).all()
    types = {row.id: row.vehicle_type for row in configured}
    if ids:
        selected = [unit for unit in units if unit.id in ids]
        return selected, len(ids), len(selected) != len(ids), 0
    applicable = set(task.applicable_vehicle_types or [])
    wanted = {kind} if kind else applicable
    selected = [unit for unit in units if not wanted or types.get(unit.vehicle_id) in wanted]
    matching = [row for row in configured if not wanted or row.vehicle_type in wanted]
    if kind:
        return selected, max(sum(row.quantity or 0 for row in matching), len(selected)), not matching, 0
    credit = db.query(VehicleProgressMigration).filter_by(project_id=project.id, step_key=step.key).one_or_none() if step else None
    if step and step.expected_quantity is not None:
        expected, unknown = step.expected_quantity, False
    else:
        expected = max(sum(row.quantity or 0 for row in matching), len(selected)) if applicable else total
        unknown = not matching if applicable else fleet_unknown
        unknown = unknown or bool(step and step.source_task_id and step.expected_quantity is None)
    return selected, expected, unknown, credit.unassigned_count if credit else 0


def completion_fact(db, project, cell, *, cache=None):
    task = db.get(Task, cell.task_id)
    if task is None or task.project_id != project.id:
        return {'state': 'unknown', 'is_complete': False, 'completed_count': None, 'required_count': None, 'quantity_unknown': True, 'warnings': ['原工作归属待核对']}
    key = (task.id, cell.vehicle_step_key, scope_identity(cell))
    if cache is not None and key in cache:
        actual = cache[key]
    else:
        from app.services.progress import quality_blocked_task_ids
        if not work.is_vehicle(task):
            blocked = task.id in quality_blocked_task_ids(db, [task])
            actual = {'completed_count': int(bool(task.manually_completed) and not blocked), 'expected_count': 1,
                      'quantity_unknown': False, 'warnings': ['必需或安全检查仍需核对'] if blocked else [],
                      'completion_recorded_at': task.manual_completed_at.isoformat() + 'Z' if task.manual_completed_at else None,
                      'completion_recorded_by': task.manual_completed_by}
        else:
            warnings = []
            step = db.query(ProjectVehicleStep).filter_by(project_id=project.id, key=cell.vehicle_step_key).one_or_none() if cell.vehicle_step_key else None
            if step is None or task.vehicle_step_key != cell.vehicle_step_key:
                actual = {'completed_count': None, 'expected_count': None, 'quantity_unknown': True, 'warnings': ['车辆环节尚未明确或与计划原关联不一致，请负责人核对']}
            else:
                units, expected, unknown, credits = _unit_scope(db, project, task, cell.scope or {}, step)
                unit_ids = {unit.id for unit in units}
                done = db.query(VehicleProgress).filter(VehicleProgress.project_id == project.id,
                    VehicleProgress.step_key == step.key, VehicleProgress.vehicle_unit_id.in_(unit_ids), VehicleProgress.is_done.is_(True)).all() if unit_ids else []
                from app.services.vehicle_checks import checks_for_unit
                eligible = [entry for entry in done if not any(check['task_id'] == task.id and check.get('blocker')
                    for check in checks_for_unit(db, project.id, entry.vehicle_unit_id, step.key))]
                # Legacy task-wide checks constrain the original pool too; new per-car
                # review duties are never silently attached to unidentified credits.
                from app.models import CheckItem
                from app.services.vehicle_checks import check_block_reason
                legacy_blocked = any(check_block_reason(db, task, check) for check in db.query(CheckItem).filter(
                    CheckItem.task_id == task.id, CheckItem.vehicle_unit_id.is_(None),
                    or_(CheckItem.project_id == project.id, CheckItem.project_id.is_(None))))
                if credits:
                    warnings.append('含已完成（迁移，车号未知）；不能据此声称逐台核验或已知完成日期')
                if unknown:
                    warnings.append('车辆应完成数量仍待核对')
                if expected is not None and expected > len(units):
                    warnings.append(f'尚有 {expected-len(units)} 台配置数量未关联到本范围真实车号或车型归属；不自动补造车辆')
                if len(eligible) != len(done) or legacy_blocked:
                    warnings.append('当前必需或安全检查尚未满足')
                actual = {'completed_count': len(eligible) + (credits if not legacy_blocked else 0),
                    'identified_completed': len(eligible), 'unidentified_completed': credits,
                    'expected_count': None if unknown else expected, 'quantity_unknown': unknown,
                    'actual_dates': sorted({entry.done_on.isoformat() for entry in eligible if entry.done_on}),
                    'completion_date_unknown': bool(credits or any(entry.done_on is None for entry in eligible)), 'warnings': warnings}
        if cache is not None:
            cache[key] = actual
    actual = dict(actual)
    if cell.mode == 'in_progress':
        required = None
        complete = not actual['quantity_unknown'] and actual.get('expected_count', 0) > 0 and (actual.get('completed_count') or 0) >= actual['expected_count']
    elif work.is_vehicle(task):
        identity = scope_identity(cell)
        targets = [None if row.intent_review_required else row.target_count for row in db.query(WeeklyPlanCell).filter(
            WeeklyPlanCell.project_id == project.id, WeeklyPlanCell.task_id == task.id,
            WeeklyPlanCell.week_start <= cell.week_start, WeeklyPlanCell.mode == 'finish',
            WeeklyPlanCell.vehicle_step_key == cell.vehicle_step_key,
            WeeklyPlanCell.published.is_(True), WeeklyPlanCell.is_cancelled.is_(False)) if scope_identity(row) == identity]
        if not cell.published:
            targets.append(cell.target_count)
        required = None if any(value is None for value in targets) else sum(targets)
        complete = required is not None and not actual['quantity_unknown'] and (actual.get('completed_count') or 0) >= required
    else:
        required = 1
        complete = actual.get('completed_count') == 1
    intent_unknown = bool(cell.intent_review_required)
    unknown = intent_unknown or actual['quantity_unknown'] or cell.mode == 'finish' and required is None
    if intent_unknown:
        complete = False
        actual['warnings'] = [*actual.get('warnings', []), '原计划含未知量或不能确定的车辆目标，须明确核对本周计划意图；未按0或部分已知量判完成']
    overdue = bool(not unknown and cell.published and not cell.is_cancelled and cell.mode == 'finish' and
                   cell.week_start + timedelta(days=6) < local_today(project) and not complete)
    return {**actual, 'required_count': required, 'is_complete': complete,
            'state': 'unknown' if unknown else 'completed' if complete else 'overdue' if overdue else 'in_progress' if cell.mode == 'in_progress' else 'planned',
            'overdue': overdue, 'intent_review_required': intent_unknown,
            'target_review_required': intent_unknown or cell.mode == 'finish' and work.is_vehicle(task) and cell.target_count is None}


def serialize_cell(db, project, cell, actor=None, *, cache=None):
    task = db.get(Task, cell.task_id)
    phase = work.phase_of(db, task) if task else None
    assignees = [db.get(User, identity) for identity in cell.assignee_ids or []]
    facts = completion_fact(db, project, cell, cache=cache)
    return {'id': cell.id, 'project_id': project.id, 'project_name': project.name, 'timezone': project.timezone or 'Asia/Shanghai',
        'project_status': project.status, 'task_id': cell.task_id, 'task_name': task.name if task else '原工作待核对',
        'kind': 'vehicle' if task and work.is_vehicle(task) else 'other', 'scope_key':cell.scope_key,
        'phase_id': phase.id if phase else None, 'phase_name': work.stage_label(phase.name) if phase else '',
        'group_label': work.group_of(db, task) if task else '', 'vehicle_step_key': cell.vehicle_step_key,
        **_raw(cell), 'week_end': (cell.week_start + timedelta(days=6)).isoformat(),
        'assignees': [{'id': identity, 'name': person.display_name if person else '原负责人未记录', 'active': bool(person and person.is_active)}
                      for identity, person in zip(cell.assignee_ids or [], assignees)],
        'version': cell.version or 0, 'source_metadata': cell.source_metadata, 'completion': facts,
        'created_at': cell.created_at.isoformat() + 'Z' if cell.created_at else None,
        'updated_at': cell.updated_at.isoformat() + 'Z' if cell.updated_at else None, 'updated_by': cell.updated_by,
        'published_at': cell.published_at.isoformat() + 'Z' if cell.published_at else None, 'published_by': cell.published_by,
        'permissions': {'edit': bool(actor and can_edit(project, actor)),
            'claim': bool(actor and can_claim(project, actor) and cell.published and not cell.assignee_ids and not cell.is_cancelled)}}


def weeks_metadata(db, start, weeks):
    from app.services.holidays import calendar_snapshot, calendar_year
    snapshot = calendar_snapshot(db)
    start = monday(start)
    window_end(start, weeks)
    rows = []
    for offset in range(weeks):
        begin = start + timedelta(weeks=offset)
        end = begin + timedelta(days=6)
        calendars = [calendar_year(year, snapshot) for year in range(begin.year, end.year + 1)]
        rows.append({'week_start': begin.isoformat(), 'week_end': end.isoformat(),
            'holiday_days': sorted(day for calendar in calendars for day in calendar['holidays'] if begin.isoformat() <= day <= end.isoformat()),
            'makeup_workdays': sorted(day for calendar in calendars for day in calendar['workdays'] if begin.isoformat() <= day <= end.isoformat()),
            'missing_holiday_years': [calendar['year'] for calendar in calendars if not calendar['available']],
            'holiday_sources': [{key: calendar.get(key) for key in ('year','source_name','source_url','published_on','version')} for calendar in calendars if calendar['available']]})
    return rows


def attention(db, projects, actor):
    items, unknown = [], []
    for project in projects:
        cache = {}
        for cell in db.query(WeeklyPlanCell).filter_by(project_id=project.id, published=True, is_cancelled=False):
            if actor.id not in (cell.assignee_ids or []) and not can_edit(project, actor):
                continue
            facts = completion_fact(db, project, cell, cache=cache)
            item = {'id': cell.id, 'project_id': project.id, 'project_name': project.name,
                'task_id': cell.task_id, 'name': db.get(Task, cell.task_id).name, 'week_start': cell.week_start.isoformat(),
                'state': facts['state'], 'url': f'/pm/projects/{project.id}/plan?view=weeks&week={cell.week_start}&cell={cell.id}'}
            if facts['overdue']:
                items.append(item)
            elif facts['state'] == 'unknown':
                unknown.append(item)
    return {'state': 'available', 'count': len(items), 'items': items, 'unknown_count': len(unknown), 'unknown_items': unknown}


def project_warnings(db, project, cells, actor):
    """Current warnings do not assign, move, or fabricate any plan/actual."""
    result = []
    cache = {}
    for cell in cells:
        facts = completion_fact(db, project, cell, cache=cache)
        for message in facts.get('warnings', []):
            result.append({'code': 'completion_scope', 'cell_id': cell.id, 'task_id': cell.task_id, 'message': message})
        if facts.get('target_review_required'):
            result.append({'code': 'legacy_target_review', 'cell_id': cell.id, 'message': '原计划量含未知值、小数或超出可用台数范围，原值已保留，请明确核对本周计划意图和目标'})
        if any(identity not in member_ids(project) or (person := db.get(User, identity)) is None or not person.is_active for identity in cell.assignee_ids or []):
            result.append({'code': 'assignee_changed', 'cell_id': cell.id, 'message': '原负责人已离开或账号停用，请明确交接；系统未自动改派'})
    query = db.query(WeeklyPlanCell).filter_by(project_id=project.id, is_cancelled=False)
    if not can_edit(project, actor):
        query = query.filter(WeeklyPlanCell.published.is_(True))
    all_cells = query.all()
    groups = defaultdict(list)
    for cell in all_cells:
        groups[(cell.task_id, scope_identity(cell))].append(cell)
    for (task_id, _), rows in groups.items():
        task = db.get(Task, task_id)
        if task is None or not work.is_vehicle(task):
            continue
        facts = completion_fact(db, project, rows[0], cache=cache)
        finish = [row for row in rows if row.mode == 'finish']
        planned = None if any(row.target_count is None for row in finish) else sum(row.target_count for row in finish)
        expected = facts.get('expected_count')
        if expected is None or planned is None or planned != expected:
            result.append({'code': 'target_mismatch', 'task_id': task_id, 'scope_key': rows[0].scope_key,
                'planned_count': planned, 'expected_count': expected,
                'message': f'「{task.name}」当前车辆范围与周计划完成目标需核对（已排 {planned if planned is not None else "未知"}，应完成 {expected if expected is not None else "未知"}）'})
    units = {row.id: row for row in db.query(VehicleUnit).filter_by(project_id=project.id)}
    types = {row.id: row.vehicle_type for row in db.query(Vehicle).filter_by(project_id=project.id)}
    by_work = defaultdict(dict)
    for cell in all_cells:
        by_work[cell.task_id][scope_identity(cell)] = cell
    def overlaps(left, right):
        a, b = left.scope or {}, right.scope or {}
        ai, bi = set(a.get('vehicle_unit_ids') or []), set(b.get('vehicle_unit_ids') or [])
        at, bt = a.get('vehicle_type'), b.get('vehicle_type')
        if not ai and not at or not bi and not bt:
            return True
        if ai and bi:
            return bool(ai & bi)
        if at and bt:
            return at == bt
        ids, kind = (ai, bt) if ai else (bi, at)
        return any(identity in units and types.get(units[identity].vehicle_id) == kind for identity in ids)
    for task_id, scopes in by_work.items():
        task = db.get(Task, task_id)
        rows = list(scopes.values())
        if task and work.is_vehicle(task) and any(overlaps(a, b) for index, a in enumerate(rows) for b in rows[index+1:]):
            result.append({'code': 'scope_overlap', 'task_id': task_id,
                'message': f'「{task.name}」存在重叠选车范围，请人工核对各周目标；同一实车完成不能据此当作两份新增事实'})
    if cells:
        start = min(cell.week_start for cell in cells)
        end = max(cell.week_start for cell in cells) + timedelta(days=6)
        identities = {identity for cell in cells for identity in cell.assignee_ids or []}
        from app.services.availability import unavailability_for_viewer
        for unavailable in db.query(UserUnavailability).filter(UserUnavailability.user_id.in_(identities),
                UserUnavailability.start_date <= end, UserUnavailability.end_date >= start):
            affected = [cell for cell in cells if unavailable.user_id in (cell.assignee_ids or []) and
                        unavailable.start_date <= cell.week_start + timedelta(days=6) and unavailable.end_date >= cell.week_start]
            if affected:
                person = db.get(User, unavailable.user_id)
                result.append({'code': 'unavailable', 'cell_ids': [cell.id for cell in affected],
                    'user_id': unavailable.user_id, 'message': f'{person.display_name if person else "原负责人"}在所排周内有不可用时段，请确认安排',
                    'unavailability': unavailability_for_viewer(db, actor, unavailable, person.display_name if person else '')})
        # Dates/counts may be shared, private project names and task text may not.
        other_rows = db.query(WeeklyPlanCell, Project).join(Project, Project.id == WeeklyPlanCell.project_id).filter(
            WeeklyPlanCell.project_id != project.id, WeeklyPlanCell.week_start >= start,
            WeeklyPlanCell.week_start <= end, WeeklyPlanCell.published.is_(True),
            WeeklyPlanCell.is_cancelled.is_(False), Project.deleted_at.is_(None), Project.status.in_(ACTIVE_PROJECT_STATUSES)).all()
        from app.services.scope import visible_project_ids
        visible = set(visible_project_ids(db, actor))
        for cell in cells:
            for identity in cell.assignee_ids or []:
                conflicts = {(row.project_id, p.name if row.project_id in visible else None)
                             for row, p in other_rows if row.week_start == cell.week_start and identity in (row.assignee_ids or [])}
                if conflicts:
                    person = db.get(User, identity)
                    result.append({'code': 'cross_project', 'cell_id': cell.id, 'user_id': identity,
                        'other_project_count': len(conflicts), 'visible_project_names': [name for _, name in sorted(conflicts) if name],
                        'message': f'{person.display_name if person else "原负责人"}同周还被安排到 {len(conflicts)} 个项目，请人工确认；不会自动负载均衡'})
    unique = {json.dumps(item, sort_keys=True, ensure_ascii=False): item for item in result}
    return list(unique.values())


def project_view(db, project, actor, start, weeks, *, include_cancelled=False):
    editing = can_edit(project, actor)
    if include_cancelled:
        if not editing:raise HTTPException(403, '仅周计划维护者可核对已取消计划')
        begin=monday(start)
        cells=db.query(WeeklyPlanCell).filter(WeeklyPlanCell.project_id==project.id,WeeklyPlanCell.week_start>=begin,WeeklyPlanCell.week_start<=window_end(begin,weeks)).order_by(WeeklyPlanCell.week_start,WeeklyPlanCell.task_id,WeeklyPlanCell.id).all()
    else:
        cells = select_cells(db, [project.id], start, weeks, published_only=not editing)
    cache = {}
    data = [serialize_cell(db, project, cell, actor, cache=cache) for cell in cells]
    phases = {}
    for task in work.tasks_query(db, [project.id]).order_by(Task.sort_order, Task.id):
        phase = work.phase_of(db, task)
        group = phases.setdefault(phase.id, {'id': phase.id, 'name': work.stage_label(phase.name),
            'source_name': phase.name, 'sort_order': phase.sort_order or 0, 'stage_key': phase.stage_key, 'work_items': []})
        group['work_items'].append({'id': task.id, 'name': task.name, 'kind': 'vehicle' if work.is_vehicle(task) else 'other',
            'group_label': work.group_of(db, task), 'vehicle_step_key': task.vehicle_step_key,
            'version': task.version or 0, 'applicable_vehicle_types': task.applicable_vehicle_types or []})
    warnings = project_warnings(db, project, cells, actor)
    metadata = weeks_metadata(db, start, weeks)
    missing = sorted({year for week in metadata for year in week['missing_holiday_years']})
    if missing:
        warnings.append({'code': 'missing_holiday_years', 'years': missing, 'message': f'缺少 {"、".join(map(str, missing))} 年已核对节假日数据，请在设置维护，不能视为全年无节假日'})
    members = db.query(User).filter(User.id.in_(member_ids(project))).order_by(User.display_name, User.id).all()
    from app.services.template_stages import stage_order
    return {'cells': data, 'work_items': sorted(phases.values(), key=lambda row: (stage_order(row['stage_key']), row['sort_order'], row['id'])),
        'weeks': metadata, 'warnings': warnings, 'timezone': project.timezone or 'Asia/Shanghai',
        'permissions': {'read': True, 'edit': editing, 'publish': editing,
            'claim': can_claim(project, actor), 'export': has_permission(actor, 'project.export', default=True) and 'project.export' in project_capabilities(actor, project)},
        'members': [{'id': person.id, 'name': person.display_name, 'active': person.is_active} for person in members],
        'vehicles': [{'id': unit.id, 'label': unit.fleet_no or unit.asset_code, 'vehicle_id': unit.vehicle_id} for unit in db.query(VehicleUnit).filter_by(project_id=project.id).order_by(VehicleUnit.asset_code)],
        'vehicle_types': sorted({row.vehicle_type for row in db.query(Vehicle).filter_by(project_id=project.id)}),
        'settings': {'rest_mode': project.rest_mode, 'rest_days': project.rest_days or [], 'skip_holidays': bool(project.skip_holidays)},
        'summary': {'state': 'available', 'published_count': sum(row['published'] and not row['is_cancelled'] for row in data),
            'draft_count': sum(not row['published'] and not row['is_cancelled'] for row in data) if editing else None, 'cancelled_count':sum(row['is_cancelled'] for row in data),
            'overdue_count': sum(row['completion']['overdue'] for row in data),
            'in_progress_count': sum(row['mode'] == 'in_progress' and not row['is_cancelled'] for row in data), 'unassigned_count':sum(not row['assignee_ids'] and not row['is_cancelled'] for row in data), 'warning_count': len(warnings)}}


def draft_preview(db, project, actor, rules, *, first_week=None):
    """Preview explicit phase/event intent; no rows or unavailability guesses."""
    if not can_edit(project, actor):
        raise HTTPException(403, '当前项目或账号不能维护周计划')
    from app.models import ProjectEvent
    events = {event.event_key: event for event in db.query(ProjectEvent).filter_by(project_id=project.id)}
    warnings, proposals = [], []
    seen, phases = set(), {}
    for rule in rules:
        phase = work.assert_phase(db, rule['phase_id'], project_id=project.id)
        if phase.id in seen:
            raise HTTPException(400, '同一工作阶段不能重复指定初稿规则')
        seen.add(phase.id); phases[phase.id] = phase
    for rule in sorted(rules, key=lambda rule: (phases[rule['phase_id']].sort_order or 0, rule['phase_id'])):
        phase = phases[rule['phase_id']]
        anchor = rule['anchor']
        event = events.get('ship' if anchor == 'before_ship' else 'arrival_all')
        anchor_date = (event.actual_date or (event.actual_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(project.timezone or 'Asia/Shanghai')).date()
                       if event.actual_at else event.planned_date)) if event else None
        if anchor_date is None:
            warnings.append({'phase_id': phase.id, 'code': 'missing_anchor', 'message': f'「{work.stage_label(phase.name)}」缺少{"发车" if anchor == "before_ship" else "全部到场"}关键日期，未编造日期'})
            continue
        offset = rule.get('offset_weeks', 0)
        try:
            begin = monday(anchor_date) + timedelta(weeks=-offset if anchor == 'before_ship' else offset)
        except OverflowError:
            raise HTTPException(400, '关键日期与周偏移超出有效日期范围') from None
        if first_week and begin < monday(first_week):
            warnings.append({'phase_id': phase.id, 'code': 'past_anchor', 'message': '该阶段规则落在所选起始周以前，保留实际锚点，请人工核对'})
        tasks = work.tasks_query(db, [project.id]).filter(Task.phase_id == phase.id).order_by(Task.sort_order, Task.id).all()
        for task in tasks:
            if db.query(WeeklyPlanCell.id).filter_by(project_id=project.id, task_id=task.id, is_cancelled=False).first():
                warnings.append({'task_id': task.id, 'code': 'already_planned', 'message': f'「{task.name}」已有周计划，初稿不会覆盖或自动移动'})
                continue
            mode, count = rule.get('mode', 'finish'), None
            if work.is_vehicle(task):
                step = db.query(ProjectVehicleStep).filter_by(project_id=project.id, key=task.vehicle_step_key).one_or_none() if task.vehicle_step_key else None
                if mode == 'finish':
                    if step is None:
                        warnings.append({'task_id': task.id, 'code': 'unmapped_step', 'message': f'「{task.name}」尚未关联真实环节，未生成猜测完成目标'})
                        continue
                    _, expected, unknown, _ = _unit_scope(db, project, task, {}, step)
                    if unknown or expected <= 0:
                        warnings.append({'task_id': task.id, 'code': 'unknown_target', 'message': f'「{task.name}」应完成台数待核对，未生成0台或猜测目标'})
                        continue
                    count = expected
            proposals.append({'task_id': task.id, 'task_name': task.name, 'phase_id': phase.id,
                'phase_name': work.stage_label(phase.name), 'kind': 'vehicle' if work.is_vehicle(task) else 'other',
                'scope': {'vehicle_unit_ids': []}, 'vehicle_step_key': task.vehicle_step_key,
                'week_start': begin.isoformat(), 'week_end': (begin + timedelta(days=6)).isoformat(),
                'mode': mode, 'target_count': count, 'assignee_ids': [], 'published': False,
                'notes': f'初稿：按{work.stage_label(phase.name)}阶段与关键事件规则生成',
                'anchor': anchor, 'anchor_date': anchor_date.isoformat(), 'offset_weeks': offset})
    tasks = work.tasks_query(db, [project.id]).order_by(Task.id).all()
    rows = db.query(WeeklyPlanCell).filter_by(project_id=project.id).order_by(WeeklyPlanCell.id).all()
    fingerprint = {'project_id': project.id, 'version': project.version or 0,
        'actor': actor.id, 'permission_version': actor.permission_version or 0,
        'rules': rules, 'first_week': first_week.isoformat() if first_week else None,
        'tasks': [(task.id, task.version or 0, task.phase_id, task.vehicle_step_key) for task in tasks],
        'existing': [(row.id, row.version or 0, row.is_cancelled) for row in rows], 'proposals': proposals, 'warnings': warnings}
    token = sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'proposals': proposals, 'warnings': warnings, 'preview_token': token,
            'meaning': '只生成未发布初稿；不自动分配人员，不使用工时、倍率或按日数量规则'}


def draft(db, project, actor, rules, *, first_week=None, preview_token):
    project = lock_authority(db, project, actor)
    preview = draft_preview(db, project, actor, rules, first_week=first_week)
    if preview['preview_token'] != preview_token:
        raise HTTPException(409, '关键日期、工作范围或周计划已变化；原输入保留，请重新预览核对')
    created = []
    for proposal in preview['proposals']:
        values = {key: proposal[key] for key in ('task_id', 'scope', 'mode', 'target_count', 'assignee_ids', 'notes')}
        values['week_start'] = date.fromisoformat(proposal['week_start'])
        values['_draft_source'] = {'kind': 't40_event_draft', 'anchor': proposal['anchor'], 'anchor_date': proposal['anchor_date'],
            'offset_weeks': proposal['offset_weeks'], 'intent_only': True}
        row = create(db, project, actor, values, already_locked=True)
        created.append(row.id)
    log_change(db, project.id, 'weekly_plan', project.id, 'draft', actor.id,
               f'按明确阶段与关键事件生成 {len(created)} 格初稿；未自动分配人员', None,
               {'rules': rules, 'created_ids': created, 'warnings': preview['warnings']})
    db.flush()
    return {'created_ids': created, 'warnings': preview['warnings'], 'count': len(created)}


def settings_view(db, project):
    from app.services.holidays import calendar_in_range
    calendar = calendar_in_range(project.start_date, project.end_date, db)
    warnings = []
    if calendar['missing_holiday_years']:
        warnings.append({'code':'missing_holiday_years', 'years':calendar['missing_holiday_years'],
                         'message':'项目周期跨入缺少已核对节假日数据的年份，请在设置维护或导入'})
    return {'settings': {'rest_mode':project.rest_mode, 'rest_days':project.rest_days or [],
            'skip_holidays':bool(project.skip_holidays)}, 'version':project.version or 0,
            'warnings':warnings, **calendar}


def save_settings(db, project, actor, values):
    project = lock_authority(db, project, actor)
    bump_version(project, values['version'])
    old = settings_view(db, project)['settings']
    project.rest_mode = {'single':'one', 'double':'two'}.get(values['rest_mode'], values['rest_mode'])
    project.rest_days = sorted({day.isoformat() for day in values['rest_days']})
    project.skip_holidays = values['skip_holidays']
    log_change(db, project.id, 'weekly_plan_settings', project.id, 'update', actor.id,
               '修改周计划休息与节假日设置；既有周格不自动移动', old, settings_view(db, project)['settings'])
    db.flush()


def project_summary(db, project, actor):
    """A visible current weekly summary; preserved daily sources never count."""
    editing=can_edit(project,actor)
    rows=db.query(WeeklyPlanCell).filter_by(project_id=project.id,is_cancelled=False)
    if not editing:rows=rows.filter(WeeklyPlanCell.published.is_(True))
    rows=rows.order_by(WeeklyPlanCell.week_start,WeeklyPlanCell.id).all()
    warnings=project_warnings(db,project,rows,actor)
    cache={};overdue=unknown=0
    for cell in rows:
        fact=completion_fact(db,project,cell,cache=cache)
        overdue+=int(fact['overdue']);unknown+=int(fact['state']=='unknown')
    return {'state':'available','total':len(rows),'published_count':sum(row.published for row in rows),
        'draft_count':sum(not row.published for row in rows) if editing else None,
        'overdue_count':overdue,'unknown_count':unknown,'unassigned_count':sum(not row.assignee_ids for row in rows),
        'warning_count':len(warnings),'warnings':warnings,
        'meaning':'真实周计划；原按日日程只读来源不计入当前安排'}


STANDARD_PHASE_ORIGINS = {
    'phase-01': ('5', '进场准备'), 'phase-02': ('6', '到货检查'),
    'phase-03': ('6', '单车调试'), 'phase-04': ('6', '地图与站点'),
    'phase-05': ('6', '系统部署'), 'phase-06': ('6', '联调工作'),
    'phase-07': ('6', '试运行工作'), 'phase-08': ('6', '培训验收'),
}


def _phase_origins(db, task):
    """Follow frozen definition identities; task/phase names never classify work."""
    result=set()
    def walk(value, depth=0):
        if not isinstance(value,dict) or depth>32:return
        phase=value.get('phase')
        if isinstance(phase,dict) and phase.get('id') in STANDARD_PHASE_ORIGINS:
            result.add(phase['id'])
        for key in ('original','source'):
            walk(value.get(key),depth+1)
    walk(task.legacy_work_snapshot)
    if task.phase_id in STANDARD_PHASE_ORIGINS:result.add(task.phase_id)
    if task.source_task_id:
        source=db.get(Task,task.source_task_id)
        if source is not None and source.project_id is None:
            phase=work.phase_of(db,source)
            if phase and phase.id in STANDARD_PHASE_ORIGINS:result.add(phase.id)
            walk(source.legacy_work_snapshot)
    return result


def _event_date(project, event, *, planned_only=False):
    if event is None:return None
    if not planned_only:
        if event.actual_date:return event.actual_date
        if event.actual_at:
            return event.actual_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(project.timezone or 'Asia/Shanghai')).date()
    return event.planned_date


def default_draft_rules(db, project, actor):
    """Reviewable calendar suggestions from exact standard definition origins.

    These are planning heuristics, not durations or execution evidence. Unknown
    custom/mixed definitions remain explicitly unclassified for manual choice.
    """
    if not can_edit(project,actor):raise HTTPException(403,'当前项目或账号不能维护周计划')
    from app.models import ProjectEvent
    events={row.event_key:row for row in db.query(ProjectEvent).filter_by(project_id=project.id)}
    grouped={}
    for task in work.tasks_query(db,[project.id]).order_by(Task.sort_order,Task.id):
        phase=work.phase_of(db,task)
        group=grouped.setdefault(phase.id,{'phase':phase,'origins':set(),'tasks':[],'unknown_source':False})
        origins=_phase_origins(db,task)
        group['origins'].update(origins);group['tasks'].append(task.id)
        group['unknown_source'] = group['unknown_source'] or not origins
    groups=sorted(grouped.values(),key=lambda row:(row['phase'].sort_order or 0,row['phase'].id))
    before=[];after=[];warnings=[]
    for group in groups:
        keys={STANDARD_PHASE_ORIGINS[origin][0] for origin in group['origins']}
        if len(keys)!=1 or group['unknown_source']:
            warnings.append({'code':'unknown_phase_origin' if not keys else 'mixed_phase_origin','phase_id':group['phase'].id,
                'message':f'「{work.stage_label(group["phase"].name)}」缺少一致的标准阶段来源；请明确选择发车前或到场后规则，系统未按名称或sort数字猜测'})
            continue
        (before if next(iter(keys))=='5' else after).append(group)
    ship=_event_date(project,events.get('ship'))
    arrival=_event_date(project,events.get('arrival_all'))
    # The end of the planning window is an explicit plan, not an inferred actual.
    acceptance=_event_date(project,events.get('acceptance'),planned_only=True)
    finish=acceptance or project.end_date
    rules=[];suggestions=[]
    def add(group,anchor,offset,begin,end,goal,reason):
        origins=sorted(group['origins'])
        rule={'phase_id':group['phase'].id,'anchor':anchor,'offset_weeks':offset,'mode':'finish'}
        rules.append(rule)
        suggestions.append({**rule,'phase_name':work.stage_label(group['phase'].name),
            'source_phase_id':origins[0] if len(origins)==1 else None,
            'source_label':'、'.join(f'{identity} {STANDARD_PHASE_ORIGINS[identity][1]}' for identity in origins),
            'window_start':begin.isoformat() if begin else None,'window_end':end.isoformat() if end else None,
            'week_start':goal.isoformat() if goal else None,'reason':reason})
    if before and ship is None:
        warnings.append({'code':'missing_ship_date','message':'标准发车前阶段缺少实际或计划发车日期，未编造默认计划周'})
    elif before:
        ship_week=monday(ship)
        try:
            first=ship_week-timedelta(weeks=len(before))
            end=ship_week-timedelta(days=1)
            for index,group in enumerate(before):
                offset=len(before)-index
                goal=ship_week-timedelta(weeks=offset)
                add(group,'before_ship',offset,first,end,goal,
                    f'按冻结标准来源建议发车前完成：以发车周 {ship_week} 倒推，当前阶段顺序偏移 {offset} 周（至少1周）；这是可调整初稿，不代表工时或实际发生')
        except OverflowError:
            warnings.append({'code':'invalid_before_ship_window','message':'发车日期倒推超出有效日期范围，请先核对关键日期'})
    if after and (arrival is None or finish is None):
        warnings.append({'code':'missing_arrival_window','message':'标准现场阶段缺少全部到场日期或计划验收/结束日期，未编造默认窗口'})
    elif after:
        start=monday(arrival);end=monday(finish)
        if end<start:
            warnings.append({'code':'invalid_arrival_window','message':'计划验收/结束日期早于到场日期，请先核对关键日期；未猜测新窗口'})
        else:
            span=(end-start).days//7
            for index,group in enumerate(after):
                offset=(index*span)//(len(after)-1) if len(after)>1 else 0
                goal=start+timedelta(weeks=offset)
                add(group,'after_arrival',offset,start,end,goal,
                    f'按当前阶段顺序在到场周 {start} 至{"计划验收" if acceptance else "项目计划结束"}周 {end} 均分；第一个阶段从0周开始，窗口较短时允许同周重叠，不使用工时、倍率或自动人员分配')
    return {'rules':rules,'suggestions':suggestions,'warnings':warnings}
