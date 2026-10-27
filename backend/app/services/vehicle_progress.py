"""Vehicle-by-step facts, frozen scope and explicit unidentified legacy credits."""
from sqlalchemy.orm import Session
from app.models import (Project, Vehicle, VehicleUnit, VehicleStep, ProjectVehicleStep,
                        VehicleProgress, VehicleProgressMigration)

DEFAULT_STEPS = [('arrival_inspection','到场点检'), ('single_commissioning','单车调试'),
                 ('map_stations','地图与站点'), ('system_integration','系统联调'), ('go_live','上线运行')]
from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
WRITE_STATUSES = frozenset(EXECUTION_PROJECT_STATUSES)


def template_steps(db: Session, template_id: str):
    return db.query(VehicleStep).filter_by(template_id=template_id).order_by(VehicleStep.sort_order, VehicleStep.key).all()


def initialize_project(db: Session, project: Project, template_id=None):
    if db.query(ProjectVehicleStep.id).filter_by(project_id=project.id).first():
        return
    rows=template_steps(db, template_id or project.template_id or 'default')
    definitions=[(r.key,r.name) for r in rows] if rows else DEFAULT_STEPS
    for i,(key,name) in enumerate(definitions):
        db.add(ProjectVehicleStep(project_id=project.id,key=key,name=name,sort_order=i))
    db.flush()


def copy_template_steps(db, source, target):
    definitions=template_steps(db, source or 'default')
    db.query(VehicleStep).filter_by(template_id=target or 'default').delete()
    for i,(key,name) in enumerate([(r.key,r.name) for r in definitions] or DEFAULT_STEPS):
        db.add(VehicleStep(template_id=target or 'default',key=key,name=name,sort_order=i))


def project_steps(db, pid):
    return db.query(ProjectVehicleStep).filter_by(project_id=pid).order_by(ProjectVehicleStep.sort_order,ProjectVehicleStep.key).all()


def fleet_scope(db,pid):
    configured=db.query(Vehicle).filter_by(project_id=pid).all()
    units=db.query(VehicleUnit).filter_by(project_id=pid).order_by(VehicleUnit.asset_code).all()
    expected=sum(max(0,v.quantity or 0) for v in configured)
    # A completely unconfigured fleet has unknown quantity, not zero work.
    return units, max(expected,len(units)), not configured


def progress_totals_batch(db,pids):
    from sqlalchemy import func
    pids=list(pids)
    if not pids:return {}
    steps=db.query(ProjectVehicleStep).filter(ProjectVehicleStep.project_id.in_(pids)).all()
    fleet={pid:(quantity or 0,count) for pid,quantity,count in db.query(Vehicle.project_id,func.sum(Vehicle.quantity),func.count(Vehicle.id)).filter(Vehicle.project_id.in_(pids)).group_by(Vehicle.project_id)}
    unit_counts=dict(db.query(VehicleUnit.project_id,func.count(VehicleUnit.id)).filter(VehicleUnit.project_id.in_(pids)).group_by(VehicleUnit.project_id))
    done={(pid,key):count for pid,key,count in db.query(VehicleProgress.project_id,VehicleProgress.step_key,func.count(VehicleProgress.id)).filter(VehicleProgress.project_id.in_(pids),VehicleProgress.is_done.is_(True)).group_by(VehicleProgress.project_id,VehicleProgress.step_key)}
    credits={(r.project_id,r.step_key):r for r in db.query(VehicleProgressMigration).filter(VehicleProgressMigration.project_id.in_(pids))}
    result={}
    for pid in pids:
        configured,config_count=fleet.get(pid,(0,0));known_units=unit_counts.get(pid,0)
        quantity=max(configured,known_units);quantity_unknown=False
        target=completed=identified=0
        for step in (s for s in steps if s.project_id==pid):
            credit=credits.get((pid,step.key))
            legacy_unknown=step.expected_quantity is None and (step.source_task_id is not None or credit and (credit.source_metadata or {}).get('quantity_unknown'))
            if legacy_unknown or (step.expected_quantity is None and not legacy_unknown and not config_count):quantity_unknown=True
            target+=step.expected_quantity if step.expected_quantity is not None else (0 if legacy_unknown else quantity)
            count=done.get((pid,step.key),0);identified+=count
            completed+=count+(credit.unassigned_count if credit else 0)
        result[pid]={'target':target,'completed':completed,'identified_completed':identified,
            'unidentified_completed':sum(r.unassigned_count for (cpid,_),r in credits.items() if cpid==pid),
            'quantity_unknown':quantity_unknown,'fleet_quantity_unknown':not config_count,'unregistered_quantity':max(0,quantity-known_units),
            'percent':None if quantity_unknown else (round(completed/target*100,1) if target else 0)}
    return result


def progress_totals(db,pid):
    return progress_totals_batch(db,[pid])[pid]


def matrix_completion_blockers(db,pid):
    totals=progress_totals(db,pid)
    if not project_steps(db,pid):
        return []
    if totals['quantity_unknown']:return ['车辆环节应完成数量未知，请先核对数量']
    return ['车辆进度表尚未全部完成'] if totals['completed']<totals['target'] else []


def migration_warnings(db,pid):
    totals=progress_totals(db,pid)
    result=[]
    if totals['quantity_unknown']: result.append('车辆数量未知，请补充车型与数量，或核对历史环节应完成台数')
    elif totals['fleet_quantity_unknown']: result.append('车型总台数尚未配置；历史环节保留已知应完成台数')
    if totals['unregistered_quantity']: result.append('部分车辆车号尚未建档')
    if totals['unidentified_completed']: result.append('已完成（迁移，车号未知）：尚未逐台核对')
    return result


def derive_stage(db,unit):
    done={p.step_key for p in db.query(VehicleProgress).filter_by(vehicle_unit_id=unit.id,is_done=True).all()}
    last=next((s for s in reversed(project_steps(db,unit.project_id)) if s.key in done),None)
    # Old lifecycle stage_after values stay in immutable historical event records.
    unit.current_stage=last.key if last else 'planned'


def matrix(db,pid):
    steps=project_steps(db,pid)
    units,_,_=fleet_scope(db,pid)
    types={v.id:v for v in db.query(Vehicle).filter_by(project_id=pid).all()}
    facts=db.query(VehicleProgress).filter_by(project_id=pid).all()
    credits=db.query(VehicleProgressMigration).filter_by(project_id=pid).all()
    def fact(p):
        return {'version':p.version,'is_done':p.is_done,'done_on':p.done_on.isoformat() if p.done_on else None,
                'recorded_at':p.recorded_at.isoformat(),'done_by':p.done_by,'note':p.note or '', 'migrated':p.migrated,'source_metadata':p.source_metadata}
    return {'project_id':pid,'steps':[{'key':s.key,'name':s.name,'source_task_id':s.source_task_id,
        'expected_quantity':s.expected_quantity} for s in steps],
        'units':[{'id':u.id,'asset_code':u.asset_code,'fleet_no':u.fleet_no or '',
            'vehicle_type':types[u.vehicle_id].vehicle_type if u.vehicle_id in types else '',
            'model_name':types[u.vehicle_id].model_name if u.vehicle_id in types else u.model_name or '',
            'current_stage':u.current_stage,'cells':{p.step_key:fact(p) for p in facts if p.vehicle_unit_id==u.id}} for u in units],
        'migration_warnings':migration_warnings(db,pid), 'legacy':[{'step_key':c.step_key,'total_count':c.total_count,'unassigned_count':c.unassigned_count,
                   'source_metadata':c.source_metadata} for c in credits], 'summary':progress_totals(db,pid)}


def parse_snapshot(payload):
    """Validate portable matrix before any import rows or files are created."""
    from datetime import date, datetime
    value=payload.get('vehicle_progress_matrix')
    if value is None: return None
    if not isinstance(value,dict): raise ValueError('vehicle_progress_matrix必须是对象')
    for key in ('steps','units','legacy'):
        if not isinstance(value.get(key),list): raise ValueError(f'车辆进度{key}必须是数组')
    keys=set()
    for step in value['steps']:
        if not isinstance(step,dict) or not isinstance(step.get('key'),str) or not 1<=len(step['key'])<=80 or not isinstance(step.get('name'),str) or not 1<=len(step['name'])<=300:
            raise ValueError('车辆环节标识或名称无效')
        if step['key'] in keys: raise ValueError('车辆环节标识重复')
        keys.add(step['key'])
        source=step.get('source_task_id')
        if source is not None and (not isinstance(source,str) or len(source)>36):raise ValueError('历史环节来源任务标识无效')
        qty=step.get('expected_quantity')
        if qty is not None and (type(qty) is not int or qty<0): raise ValueError('历史环节目标台数无效')
    if not keys: raise ValueError('车辆进度表必须保留至少一个环节')
    exported={r.get('source_id') for r in payload.get('vehicle_units',[]) if isinstance(r,dict)}
    unit_ids=set(); migrated={}
    for unit in value['units']:
        if not isinstance(unit,dict) or unit.get('id') not in exported or unit.get('id') in unit_ids or not isinstance(unit.get('cells'),dict):
            raise ValueError('车辆进度引用的真实车辆不存在或重复')
        unit_ids.add(unit['id'])
        for key,fact in unit['cells'].items():
            if key not in keys or not isinstance(fact,dict) or type(fact.get('is_done')) is not bool or type(fact.get('migrated')) is not bool:
                raise ValueError('车辆进度单元格无效')
            if type(fact.get('version')) is not int or fact['version']<1: raise ValueError('车辆进度版本无效')
            if fact.get('done_on'):
                from app.time_utils import project_today
                if date.fromisoformat(fact['done_on'])>project_today((payload.get('project') or {}).get('timezone')):
                    raise ValueError('车辆环节完成日期不能晚于项目当地今天')
            if fact['is_done'] and not fact.get('done_on') and not fact['migrated']: raise ValueError('实际完成环节缺少完成日期')
            if not isinstance(fact.get('recorded_at'),str): raise ValueError('车辆进度缺少原登记时间')
            datetime.fromisoformat(fact['recorded_at'])
            if fact['is_done'] and fact['migrated']: migrated[key]=migrated.get(key,0)+1
    credit_keys=set()
    for credit in value['legacy']:
        if not isinstance(credit,dict) or credit.get('step_key') not in keys or credit['step_key'] in credit_keys:
            raise ValueError('历史车辆凭证环节无效或重复')
        credit_keys.add(credit['step_key'])
        total,remaining=credit.get('total_count'),credit.get('unassigned_count')
        if type(total) is not int or type(remaining) is not int or remaining<0 or total<remaining:
            raise ValueError('历史车辆凭证数量无效')
        if remaining+migrated.get(credit['step_key'],0)!=total: raise ValueError('历史车辆凭证与真实车辆补录数量对账不平')
        if not isinstance(credit.get('source_metadata'),dict): raise ValueError('历史车辆凭证缺少原始来源')
    if set(migrated)-credit_keys: raise ValueError('迁移单元格没有对应历史凭证')
    return value


def import_snapshot(db,project,value,task_map,unit_map,*,planning_only=False):
    from datetime import date, datetime, timezone
    if value is None:
        initialize_project(db,project)
        return
    for i,s in enumerate(value['steps']):
        source=task_map.get(s.get('source_task_id'))
        db.add(ProjectVehicleStep(project_id=project.id,key=s['key'],name=s['name'],sort_order=i,
            source_task_id=source.id if source else None,expected_quantity=s.get('expected_quantity')))
    if planning_only:
        db.flush()
        return
    for credit in value['legacy']:
        db.add(VehicleProgressMigration(project_id=project.id,step_key=credit['step_key'],total_count=credit['total_count'],
            unassigned_count=credit['unassigned_count'],source_metadata=credit['source_metadata']))
    for u in value['units']:
        for key,f in u['cells'].items():
            recorded=datetime.fromisoformat(f['recorded_at'])
            if recorded.tzinfo: recorded=recorded.astimezone(timezone.utc).replace(tzinfo=None)
            db.add(VehicleProgress(project_id=project.id,vehicle_unit_id=unit_map[u['id']].id,step_key=key,is_done=f['is_done'],
                done_on=date.fromisoformat(f['done_on']) if f.get('done_on') else None,recorded_at=recorded,done_by=None,
                note=f.get('note',''),migrated=f['migrated'],version=f['version'],source_metadata=f))
    db.flush()
    for u in unit_map.values(): derive_stage(db,u)



def retain_portable_source(project,payload,*,source_project_id=None):
    """Keep every original execution field for inspection, never as qualification."""
    from copy import deepcopy
    from app.time_utils import utcnow
    project.portable_unverified_snapshot={
        'read_only':True,'verified':False,'source_project_id':source_project_id,
        'recorded_at':utcnow().isoformat(),
        'meaning':'来源执行事实仅供核对，新项目须重新登记完成、检查和验收。',
        'vehicle_progress_matrix':deepcopy(payload.get('vehicle_progress_matrix')),
        'execution_evidence':deepcopy(payload.get('execution_evidence')),
        'field_operation_evidence':deepcopy(payload.get('field_operation_evidence')),
        'legacy_quantity_reports':deepcopy(payload.get('progress',[])),
        'legacy_daily_plans':deepcopy(payload.get('schedule',[])),
        'legacy_work_items':deepcopy(payload.get('legacy_work_items',[])),
        'legacy_planning_schedule':deepcopy(payload.get('planning_schedule')),
        'legacy_planning_source':deepcopy(payload.get('legacy_planning_source')),
        'weekly_plan_source':deepcopy(payload.get('weekly_plan_source')),
        'prior_portable_unverified_snapshot':deepcopy(payload.get('portable_unverified_snapshot'))}
