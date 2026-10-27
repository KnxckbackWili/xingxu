"""Equal-weight vehicle steps and non-vehicle work; original quantities remain facts."""

from sqlalchemy import case, func, and_, or_
from sqlalchemy.orm import Session
from app.models import Task, DailyProgress, CheckItem, ScheduleEntry, Module, Phase
from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES


def execution_tasks_for_projects(db: Session, project_ids: list[str]) -> list[Task]:
    if not project_ids:
        return []
    from app.services.work_items import tasks_query
    return tasks_query(db,project_ids).all()



def execution_tasks(db: Session, project_id: str) -> list[Task]:
    return execution_tasks_for_projects(db, [project_id])


def quality_blocked_task_ids(db,tasks,checks=None):
    """checks: the tasks' already-loaded CheckItem rows, to avoid re-reading them."""
    from app.services.manual_completion import covers
    by_id={task.id:task for task in tasks}
    blocked=set()
    for check in (db.query(CheckItem).filter(CheckItem.task_id.in_(by_id)) if checks is None else checks):
        task=by_id[check.task_id]
        if check.project_id not in (None,task.project_id):continue
        safety=check.is_safety_critical and (not check.is_done or check.failed or not check.is_applicable)
        failed=check.is_applicable and check.failed and not covers(task,check)
        pending=check.is_applicable and check.is_required and not check.is_done and not check.failed and (
            task.phase_id is not None or check.vehicle_unit_id or not task.manually_completed)
        if safety or failed or pending:blocked.add(task.id)
    return blocked


def task_progress_maps(db: Session, tasks: list[Task]) -> tuple[dict, dict, dict]:
    """Batch-compute completed quantity, effective target and percent."""
    task_ids = [t.id for t in tasks]
    if not task_ids:
        return {}, {}, {}

    # 完成量按 2 位小数取整：SUM(0.1/0.9 等浮点分片) 会累积出 49.99999999999999 类误差，
    # 直接透传到前端会显示成「49.99999999999999/50」。统一在聚合处四舍五入。
    completed_map = {task_id: round(quantity or 0, 2) for task_id, quantity in (
        db.query(
            DailyProgress.task_id,
            func.coalesce(func.sum(DailyProgress.completed_quantity), 0),
        )
        .filter(DailyProgress.task_id.in_(task_ids))
        .group_by(DailyProgress.task_id)
        .all()
    )}
    check_counts = {
        task_id: (total or 0, applicable or 0, failed or 0, pending or 0, safety or 0)
        for task_id, total, applicable, failed, pending, safety in (
            db.query(
                CheckItem.task_id,
                func.count(CheckItem.id),
                func.sum(case((CheckItem.is_applicable.is_(True), 1), else_=0)),
                func.sum(case((CheckItem.failed.is_(True), 1), else_=0)),
                func.sum(case((and_(CheckItem.is_applicable.is_(True), CheckItem.is_done.is_not(True), or_(CheckItem.is_required.is_(True), CheckItem.is_safety_critical.is_(True))), 1), else_=0)),
                func.sum(case((and_(CheckItem.is_safety_critical.is_(True), or_(CheckItem.is_done.is_not(True), CheckItem.failed.is_(True), CheckItem.is_applicable.is_not(True))), 1), else_=0)),
            )
            .filter(CheckItem.task_id.in_(task_ids))
            .group_by(CheckItem.task_id)
            .all()
        )
    }

    target_map = {}
    percent_map = {}
    for task in tasks:
        target = task.target_quantity or 0
        total_checks, applicable_checks, failed_checks, pending_checks, safety_checks = check_counts.get(task.id, (0, 0, 0, 0, 0))
        if target <= 0 or (total_checks > 0 and applicable_checks == 0):
            target = 0
        completed = completed_map.get(task.id, 0)
        target_map[task.id] = target
        # 管理员可覆盖数量/普通检查，但安全检查仍须通过；实际报工不变。
        if getattr(task, "manually_completed", False):
            percent = 100.0
        else:
            percent = (
                min(100.0, round(completed / target * 100, 1))
                if target > 0 else (100.0 if total_checks > 0 and applicable_checks == 0 else 0.0)
            )
            # C5-3：存在「不通过」检查项 → 进度封顶 99%（阶段/项目进度无法到达 100%，
            # 从而阻塞完成/归档门禁，直到安全项重新通过）。不通过项本身由前端红标展示。
            if failed_checks or pending_checks:
                percent = min(percent, 99.0)
        # Safety verification remains mandatory, including managerial quantity overrides.
        if safety_checks:
            percent = min(percent, 99.0)
        percent_map[task.id] = percent
        completed_map.setdefault(task.id, 0)

    # Historical per-vehicle work now reads its frozen matrix source. Quantity
    # reports stay intact for audit, but cannot independently change this matrix.
    from app.models import ProjectVehicleStep, VehicleProgress, VehicleProgressMigration
    project_ids={t.project_id for t in tasks if t.project_id}
    snapshots=db.query(ProjectVehicleStep).filter(ProjectVehicleStep.project_id.in_(project_ids)).all() if project_ids else []
    by_source={r.source_task_id:r for r in snapshots if r.source_task_id}
    progress_counts={(pid,key):count for pid,key,count in db.query(VehicleProgress.project_id,VehicleProgress.step_key,func.count(VehicleProgress.id)).filter(VehicleProgress.project_id.in_(project_ids),VehicleProgress.is_done.is_(True)).group_by(VehicleProgress.project_id,VehicleProgress.step_key)} if project_ids else {}
    credit_map={(r.project_id,r.step_key):r for r in db.query(VehicleProgressMigration).filter(VehicleProgressMigration.project_id.in_(project_ids))} if project_ids else {}
    for task in tasks:
        step=by_source.get(task.id)
        if task.quantity_type!='per_vehicle' or step is None:
            continue
        identified=progress_counts.get((step.project_id,step.key),0)
        credit=credit_map.get((step.project_id,step.key))
        completed_map[task.id]=identified+(credit.unassigned_count if credit else 0)
        target_map[task.id]=step.expected_quantity or 0
        percent_map[task.id]=min(100,round(completed_map[task.id]/target_map[task.id]*100,1)) if target_map[task.id] else 0
        if check_counts.get(task.id,(0,0,0,0,0))[4]: percent_map[task.id]=min(percent_map[task.id],99)
    # T34 work has no editable quantity target. Preserve old raw report functions
    # for source readers, while active status uses booleans or the real matrix.
    from app.services.work_items import step_state
    quality_blocked=quality_blocked_task_ids(db,tasks)
    for task in tasks:
        if task.phase_id is None:
            continue  # compatibility for historical adapters awaiting normalization
        if task.quantity_type == 'per_vehicle':
            state=step_state(db,task)
            target_map[task.id]=state.get('expected_count') or 0
            completed_map[task.id]=state.get('completed_count') or 0
            percent_map[task.id]=state.get('percent') or 0
        else:
            target_map[task.id]=1
            completed_map[task.id]=1 if task.manually_completed else 0
            percent_map[task.id]=100 if task.manually_completed else 0
        if task.id in quality_blocked:
            percent_map[task.id]=min(percent_map[task.id],99)
    return completed_map, target_map, percent_map


def task_completed(db: Session, task_id: str) -> float:
    return round(db.query(func.coalesce(func.sum(DailyProgress.completed_quantity), 0)).filter(
        DailyProgress.task_id == task_id
    ).scalar() or 0, 2)


def effective_target(db: Session, task_id: str) -> float:
    """Target minus not-applicable check items is not subtracted (quantities stay),
    but tasks with zero applicable check items contribute nothing."""
    task = db.get(Task, task_id)
    if task is None:
        return 0
    target = task.target_quantity or 0
    if target <= 0:
        return 0
    # If ALL check items are not applicable → task contributes nothing
    items = db.query(CheckItem).filter(CheckItem.task_id == task_id).all()
    if items and not any(i.is_applicable for i in items):
        return 0
    return target


def _has_failed_check(db: Session, task_id: str) -> bool:
    return bool(db.query(CheckItem.id).filter(
        CheckItem.task_id == task_id, CheckItem.failed.is_(True)).first())


def task_progress(db: Session, task_id: str) -> float:
    """Progress 0-100 for one task."""
    task = db.get(Task, task_id)
    if task is None:
        return 0
    return task_progress_maps(db, [task])[2][task_id]


def _is_na_or_completed(db: Session, task_id: str) -> bool:
    items = db.query(CheckItem).filter(CheckItem.task_id == task_id).all()
    if items and not any(i.is_applicable for i in items):
        return True
    return False


def project_completion_blocker_tasks(db: Session, project_id: str) -> list[Task]:
    """Completion is a task invariant, never a rounded display percentage.

    Keep the explicit manual-completion override and all-not-applicable semantics.
    """
    tasks = execution_tasks(db, project_id)
    _, targets, percentages = task_progress_maps(db, tasks)
    # Display aggregates round to two decimals. The gate must use the raw sum.
    completed = dict(db.query(DailyProgress.task_id, func.sum(DailyProgress.completed_quantity))
                     .filter(DailyProgress.task_id.in_([task.id for task in tasks]))
                     .group_by(DailyProgress.task_id).all())
    quality_blocked=quality_blocked_task_ids(db,tasks)
    from app.services.work_items import step_state
    unlinked={task.id for task in tasks if task.phase_id is not None and task.quantity_type=='per_vehicle' and not step_state(db,task).get('linked')}
    return [
        task for task in tasks
        if (task.id in quality_blocked or task.id in unlinked
            or (task.quantity_type != "per_vehicle" and not task.manually_completed
                and (percentages[task.id] < 100
                     or (task.phase_id is None and targets[task.id] > 0 and (completed.get(task.id) or 0) < targets[task.id] - 1e-9))))
    ]


def project_completion_blockers(db: Session, project_id: str) -> list[str]:
    from app.services.vehicle_progress import matrix_completion_blockers
    return [task.name for task in project_completion_blocker_tasks(db, project_id)] + matrix_completion_blockers(db, project_id)


def project_progress_tree(db: Session, project_id: str) -> dict:
    """Equal real vehicle-step counts plus non-vehicle work completion."""
    from app.services.work_items import phase_of,group_of,stage_label
    from app.services.vehicle_progress import progress_totals
    tasks=execution_tasks(db,project_id)
    completed,targets,percentages=task_progress_maps(db,tasks)
    grouped={}
    for task in tasks:
        phase=phase_of(db,task)
        if phase is None:continue
        entry=grouped.setdefault(phase.id,{'id':phase.id,'name':stage_label(phase.name),'color':phase.color,
            'sort_order':phase.sort_order or 0,'work_items':[]})
        entry['work_items'].append({'id':task.id,'name':task.name,'group_label':group_of(db,task),
            'kind':'vehicle' if task.quantity_type=='per_vehicle' else 'other',
            'vehicle_step_key':task.vehicle_step_key,'target':targets.get(task.id,0),
            'completed':completed.get(task.id,0),'percent':percentages.get(task.id,0),'safety_flag':task.safety_flag})
    phases=[]
    for entry in sorted(grouped.values(),key=lambda p:(p['sort_order'],p['id'])):
        work=entry['work_items'];target=sum(w['target'] for w in work);done=sum(min(w['completed'],w['target']) for w in work)
        pct=round(sum(w['target']*w['percent']/100 for w in work)/target*100,1) if target else 0
        entry.update(target=target,completed=done,percent=pct,
            modules=[{'id':entry['id']+':source','name':entry['name'],'target':target,'completed':done,'percent':pct,'tasks':work,'read_only_source':True}])
        phases.append(entry)
    matrix=progress_totals(db,project_id)
    other=[t for t in tasks if t.quantity_type!='per_vehicle']
    target=matrix['target']+len(other)
    done=matrix['completed']+sum(percentages.get(t.id,0)>=100 for t in other)
    percent=None if matrix['quantity_unknown'] else round(done/target*100,1) if target else 0
    return {'project_id':project_id,'phases':phases,'target':target,'completed':done,'total_target':target,'total_completed':done,'overall_percent':percent,
        'calculation':'vehicle_steps_and_equal_work_items','progress_known':not matrix['quantity_unknown'],
        'quantities_by_unit':[{'unit':'车辆环节','completed':matrix['completed'],'target':matrix['target']},{'unit':'工作项','completed':sum(percentages.get(t.id,0)>=100 for t in other),'target':len(other)}],
        'percent':percent if percent is not None else 0,'vehicle_progress':matrix,'work_items_total':len(other),
        'work_items_completed':sum(percentages.get(t.id,0)>=100 for t in other)}


def plan_vs_actual_timeline(db: Session, project_id: str, from_date, to_date) -> list:
    """Published weekly finish intent and currently valid matrix completion dates."""
    from datetime import timedelta
    from app.models import Project, WeeklyPlanCell, VehicleProgress,VehicleProgressMigration
    from app.services.weekly_plans import monday
    project=db.get(Project,project_id)
    if project is None:return []
    start=monday(from_date or project.start_date)
    end=max(to_date or project.end_date,start)
    planned={}; unknown=set()
    rows=db.query(WeeklyPlanCell,Task).join(Task,Task.id==WeeklyPlanCell.task_id).filter(
        WeeklyPlanCell.project_id==project_id,WeeklyPlanCell.published.is_(True),WeeklyPlanCell.is_cancelled.is_(False),
        WeeklyPlanCell.mode=='finish',Task.quantity_type=='per_vehicle').all()
    for cell,task in rows:
        if cell.target_count is None:unknown.add(cell.week_start)
        else:planned[cell.week_start]=planned.get(cell.week_start,0)+cell.target_count
    actual={};unknown_dates=0
    for cell in db.query(VehicleProgress).filter_by(project_id=project_id,is_done=True):
        if cell.done_on is None:unknown_dates+=1;continue
        week=monday(cell.done_on);actual[week]=actual.get(week,0)+1
    unknown_dates+=sum(row.unassigned_count for row in db.query(VehicleProgressMigration).filter_by(project_id=project_id))
    result=[]
    while start<=end:
        result.append({'date':start.isoformat(),'planned':None if start in unknown else planned.get(start,0),
            'actual':actual.get(start,0),'planned_pct':None,'actual_pct':None,'period':'week','unit':'车辆环节',
            'plan_available':bool(rows),'actual_date_unknown_count':unknown_dates,'meaning':'已发布完成目标与已知实际日期；迁移未知日期不分配到任意周'})
        start+=timedelta(days=7)
    return result
