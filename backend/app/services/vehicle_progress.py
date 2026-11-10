"""Vehicle-by-step facts: which car finished which step, and when."""
from sqlalchemy.orm import Session
from app.models import Project, Vehicle, VehicleUnit, VehicleStep, ProjectVehicleStep, VehicleProgress

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
    result={}
    for pid in pids:
        configured,config_count=fleet.get(pid,(0,0));known_units=unit_counts.get(pid,0)
        quantity=max(configured,known_units);quantity_unknown=False
        target=completed=0
        for step in (s for s in steps if s.project_id==pid):
            if step.expected_quantity is None and not config_count:quantity_unknown=True
            target+=step.expected_quantity if step.expected_quantity is not None else quantity
            completed+=done.get((pid,step.key),0)
        result[pid]={'target':target,'completed':completed,
            'quantity_unknown':quantity_unknown,'unregistered_quantity':max(0,quantity-known_units),
            'percent':None if quantity_unknown else (round(completed/target*100,1) if target else 0)}
    return result


def progress_totals(db,pid):
    return progress_totals_batch(db,[pid])[pid]


def migration_warnings(db,pid):
    totals=progress_totals(db,pid)
    result=[]
    if totals['quantity_unknown']: result.append('车辆数量未知，请补充车型与数量')
    if totals['unregistered_quantity']: result.append('部分车辆车号尚未建档')
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
    def fact(p):
        return {'version':p.version,'is_done':p.is_done,'done_on':p.done_on.isoformat() if p.done_on else None,
                'recorded_at':p.recorded_at.isoformat(),'done_by':p.done_by,'note':p.note or '','source_metadata':p.source_metadata}
    return {'project_id':pid,'steps':[{'key':s.key,'name':s.name,'source_task_id':s.source_task_id,
        'expected_quantity':s.expected_quantity} for s in steps],
        'units':[{'id':u.id,'asset_code':u.asset_code,'fleet_no':u.fleet_no or '',
            'vehicle_type':types[u.vehicle_id].vehicle_type if u.vehicle_id in types else '',
            'model_name':types[u.vehicle_id].model_name if u.vehicle_id in types else u.model_name or '',
            'current_stage':u.current_stage,'cells':{p.step_key:fact(p) for p in facts if p.vehicle_unit_id==u.id}} for u in units],
        'migration_warnings':migration_warnings(db,pid), 'summary':progress_totals(db,pid)}


def parse_snapshot(payload):
    """Validate portable matrix before any import rows or files are created."""
    value=payload.get('vehicle_progress_matrix')
    if value is None: return None
    if not isinstance(value,dict) or not isinstance(value.get('steps'),list): raise ValueError('车辆进度steps必须是数组')
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
    return value


def import_snapshot(db,project,value,task_map):
    """Only the step definitions transfer; vehicle facts are recorded again in the new project."""
    if value is None:
        initialize_project(db,project)
        return
    for i,s in enumerate(value['steps']):
        source=task_map.get(s.get('source_task_id'))
        db.add(ProjectVehicleStep(project_id=project.id,key=s['key'],name=s['name'],sort_order=i,
            source_task_id=source.id if source else None,expected_quantity=s.get('expected_quantity')))
    db.flush()


