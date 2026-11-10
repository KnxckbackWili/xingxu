"""Progress: vehicle steps from the vehicle progress table, other work by completion."""

from sqlalchemy.orm import Session
from app.models import Task, CheckItem


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
    """Completed count, target and percent of each task.

    Per-vehicle work counts the cars that finished its step; other work is one
    item that is done once it is marked complete. Open required or safety checks
    cap a task at 99%.
    """
    if not tasks:
        return {}, {}, {}
    from app.services.work_items import step_states
    quality_blocked = quality_blocked_task_ids(db, tasks)
    states = step_states(db, [task for task in tasks if task.quantity_type == 'per_vehicle'])
    completed_map, target_map, percent_map = {}, {}, {}
    for task in tasks:
        if task.quantity_type == 'per_vehicle':
            state = states.get(task.id) or {}
            target_map[task.id] = state.get('expected_count') or 0
            completed_map[task.id] = state.get('completed_count') or 0
            percent_map[task.id] = state.get('percent') or 0
        else:
            target_map[task.id] = 1
            completed_map[task.id] = 1 if task.manually_completed else 0
            percent_map[task.id] = 100 if task.manually_completed else 0
        if task.id in quality_blocked:
            percent_map[task.id] = min(percent_map[task.id], 99)
    return completed_map, target_map, percent_map


def task_completed(db: Session, task_id: str) -> float:
    task = db.get(Task, task_id)
    return task_progress_maps(db, [task])[0][task_id] if task else 0


def task_progress(db: Session, task_id: str) -> float:
    """Progress 0-100 for one task."""
    task = db.get(Task, task_id)
    if task is None:
        return 0
    return task_progress_maps(db, [task])[2][task_id]


def project_completion_blocker_tasks(db: Session, project_id: str) -> list[Task]:
    """Work that keeps the project from completing: open checks, unlinked vehicle work, unfinished items."""
    tasks = execution_tasks(db, project_id)
    quality_blocked = quality_blocked_task_ids(db, tasks)
    from app.services.work_items import step_states
    vehicle_tasks = [task for task in tasks if task.quantity_type == 'per_vehicle']
    states = step_states(db, vehicle_tasks)
    unlinked = {task.id for task in vehicle_tasks if not (states.get(task.id) or {}).get('linked')}
    return [task for task in tasks
            if task.id in quality_blocked or task.id in unlinked
            or (task.quantity_type != 'per_vehicle' and not task.manually_completed)]


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
    from app.models import Project, WeeklyPlanCell, VehicleProgress
    from app.services.weekly_plans import monday
    project=db.get(Project,project_id)
    if project is None:return []
    start=monday(from_date or project.start_date)
    end=max(to_date or project.end_date,start)
    planned={}; unknown=set()
    rows=db.query(WeeklyPlanCell,Task).join(Task,Task.id==WeeklyPlanCell.task_id).filter(
        WeeklyPlanCell.project_id==project_id,WeeklyPlanCell.is_cancelled.is_(False),
        WeeklyPlanCell.mode=='finish',Task.quantity_type=='per_vehicle').all()
    for cell,task in rows:
        if cell.target_count is None:unknown.add(cell.week_start)
        else:planned[cell.week_start]=planned.get(cell.week_start,0)+cell.target_count
    actual={}
    for cell in db.query(VehicleProgress).filter_by(project_id=project_id,is_done=True):
        if cell.done_on is not None:
            week=monday(cell.done_on);actual[week]=actual.get(week,0)+1
    result=[]
    while start<=end:
        result.append({'date':start.isoformat(),'planned':None if start in unknown else planned.get(start,0),
            'actual':actual.get(start,0),'planned_pct':None,'actual_pct':None,'period':'week','unit':'车辆环节',
            'plan_available':bool(rows),'meaning':'周计划完成目标与实际完成日期'})
        start+=timedelta(days=7)
    return result
