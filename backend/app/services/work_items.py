"""Stage/work-item domain; old hierarchy and quantities remain read-only facts.

All mutations take the common Project lock before fresh reads. This module never
commits; callers own transactions. No Module is created to hold new work.
"""
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import func,or_
from app.models import (Task,Phase,Module,Project,User,CheckItem,DailyProgress,
    VehicleUnit,ProjectVehicleStep,VehicleProgress,VehicleProgressMigration)
from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES
from app.services.permissions import C_PLAN,authorize_project,project_capabilities
from app.services.system_permissions import has_permission
from app.services.record_lock import lock_writable_project,lock_record
from app.services.optimistic import bump_version
from app.services.change_log import log_change
from app.time_utils import utcnow


def stage_label(name):
    return {'系统联调':'联调工作','试运行':'试运行工作'}.get(name,name)


def is_vehicle(task):return task.quantity_type=='per_vehicle'


def phase_of(db,task):
    if task.phase_id:return db.get(Phase,task.phase_id)
    module=db.get(Module,task.module_id) if task.module_id else None
    return db.get(Phase,module.phase_id) if module and module.phase_id else None


def group_of(db,task):
    if task.phase_id:return task.group_label or ''
    module=db.get(Module,task.module_id) if task.module_id else None
    return module.name if module else task.group_label or ''


def tasks_query(db,project_ids):
    return db.query(Task).outerjoin(Module,Task.module_id==Module.id).join(
        Phase,Phase.id==func.coalesce(Task.phase_id,Module.phase_id)).filter(
        Task.project_id.in_(project_ids),Phase.name.notin_(REMINDER_ONLY_PHASE_NAMES))


def assert_phase(db,phase_id,*,project_id=None,template_id=None):
    row=db.get(Phase,phase_id)
    tid=None if template_id=='default' else template_id
    if row is None or row.project_id!=project_id or project_id is None and row.template_id!=tid:
        raise HTTPException(404,'阶段不属于当前项目或模板')
    if row.name in REMINDER_ONLY_PHASE_NAMES:raise HTTPException(400,'准备提醒已由资料清单维护，不能生成实施工作')
    return row


def lock_plan(db,project,user):
    project=lock_writable_project(db,project,user);db.refresh(user)
    if not has_permission(user,'project.manage_plan',default=True):raise HTTPException(403,'工作计划维护权限已变化')
    authorize_project(user,project,C_PLAN)
    from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES
    if project.status not in ACTIVE_PROJECT_STATUSES:raise HTTPException(400,'请先核对或恢复项目状态再维护工作定义')
    return project


def lock_work(db,project,user,task_id,version):
    row=db.get(Task,task_id)
    if row is None or row.project_id!=project.id:raise HTTPException(404,'工作项不存在')
    lock_record(db,row,conflict_detail='工作项已被其它操作更新，请刷新核对')
    bump_version(row,version)
    return row


def legacy_quantity(db,task):
    rows=db.query(DailyProgress,User.display_name).outerjoin(User,User.id==DailyProgress.user_id).filter(DailyProgress.task_id==task.id).order_by(DailyProgress.work_date,DailyProgress.id).all()
    return {'read_only':True,'meaning':'原工作数量事实，仅供追溯，不作为当前目标或新项目完成资格',
        'quantity_type':task.quantity_type,'target_quantity':task.target_quantity,'unit':task.unit,
        'completed_quantity':sum(row.completed_quantity or 0 for row,_ in rows),
        'source':task.legacy_work_snapshot,'reports':[{'id':row.id,'client_uuid':row.client_uuid,'work_date':row.work_date.isoformat(),
            'user_id':row.user_id,'user_name':name or '原操作人未记录','completed_quantity':row.completed_quantity,'note':row.note,
            'created_at':row.created_at.isoformat()+'Z' if row.created_at else None} for row,name in rows]}


def step_state(db,task):
    return step_states(db,[task]).get(task.id)


def step_states(db,tasks):
    """Vehicle-matrix state per vehicle work item; each project's steps, counts and fleet are read once."""
    from collections import defaultdict
    from app.services.vehicle_progress import fleet_scope
    by_project=defaultdict(list)
    for task in tasks:
        if task.project_id:by_project[task.project_id].append(task)
    result={}
    for project_id,rows in by_project.items():
        keys={t.vehicle_step_key for t in rows if t.vehicle_step_key}
        steps={s.key:s for s in db.query(ProjectVehicleStep).filter(ProjectVehicleStep.project_id==project_id,ProjectVehicleStep.key.in_(keys))} if keys else {}
        done=dict(db.query(VehicleProgress.step_key,func.count(VehicleProgress.id)).filter(VehicleProgress.project_id==project_id,
            VehicleProgress.step_key.in_(steps),VehicleProgress.is_done.is_(True)).group_by(VehicleProgress.step_key)) if steps else {}
        credits={c.step_key:c for c in db.query(VehicleProgressMigration).filter(VehicleProgressMigration.project_id==project_id,VehicleProgressMigration.step_key.in_(steps))} if steps else {}
        fleet=fleet_scope(db,project_id) if steps else None
        for task in rows:
            if not task.vehicle_step_key:result[task.id]={'linked':False,'complete':False,'percent':None,'warning':'尚未明确关联车辆环节'};continue
            step=steps.get(task.vehicle_step_key)
            if step is None:result[task.id]={'linked':False,'complete':False,'percent':None,'warning':'原车辆环节来源待核对'};continue
            units,total,unknown=fleet
            expected=step.expected_quantity if step.expected_quantity is not None else total
            if step.source_task_id and step.expected_quantity is None:unknown=True
            identified=done.get(step.key,0)
            credit=credits.get(step.key)
            unidentified=credit.unassigned_count if credit else 0
            count=identified+unidentified
            result[task.id]={'linked':True,'key':step.key,'name':step.name,'identified_completed':identified,'unidentified_completed':unidentified,
                'completed_count':count,'expected_count':None if unknown else expected,
                'complete':not unknown and expected>0 and count>=expected,
                'percent':None if unknown else min(100,round(count/expected*100,1)) if expected else 0,
                'warning':'已完成（迁移，车号未知），不代表逐台核验' if unidentified else '车辆数量待核对' if unknown else ''}
    return result


def item_dict(db,task,*,checks=False):
    return item_dicts(db,[task],checks=checks)[task.id]


def item_dicts(db,tasks,*,checks=False):
    """Work-item rows keyed by id; each level is loaded once for the whole list.

    A template tree lists every task, so per-task lookups here become N+1 queries.
    """
    from collections import defaultdict
    from app.models import TemplateDoc,VehicleCheckDefinition
    tasks=list(tasks)
    if not tasks:return {}
    ids=[t.id for t in tasks]
    # Phases/modules are few and usually already in the identity map; db.get reuses it.
    modules={key:db.get(Module,key) for key in {t.module_id for t in tasks if t.module_id and not t.phase_id}}
    phases={key:db.get(Phase,key) for key in {t.phase_id for t in tasks if t.phase_id}|{m.phase_id for m in modules.values() if m and m.phase_id}}
    actor_ids={t.manual_completed_by for t in tasks if t.manual_completed_by}
    actors={u.id:u for u in db.query(User).filter(User.id.in_(actor_ids))} if actor_ids else {}
    template_docs=defaultdict(list)
    template_ids=[t.id for t in tasks if not t.project_id]
    if template_ids:
        for d in db.query(TemplateDoc).filter(TemplateDoc.task_id.in_(template_ids)).order_by(TemplateDoc.uploaded_at):
            template_docs[d.task_id].append(d)
    if checks:
        from app.services.progress import quality_blocked_task_ids
        by_id={t.id:t for t in tasks}
        all_checks=db.query(CheckItem).filter(CheckItem.task_id.in_(ids)).order_by(CheckItem.sort_order,CheckItem.id).all()
        blocked=quality_blocked_task_ids(db,tasks,checks=all_checks)
        task_checks=defaultdict(list)
        for c in all_checks:
            if c.project_id in (None,by_id[c.task_id].project_id):task_checks[c.task_id].append(c)
        definitions=defaultdict(list)
        for d in db.query(VehicleCheckDefinition).filter(VehicleCheckDefinition.task_id.in_(ids)).order_by(VehicleCheckDefinition.sort_order,VehicleCheckDefinition.id):
            definitions[d.task_id].append(d)
        unit_ids={c.vehicle_unit_id for rows in task_checks.values() for c in rows if c.vehicle_unit_id}
        units={u.id:u for u in db.query(VehicleUnit).filter(VehicleUnit.id.in_(unit_ids))} if unit_ids else {}
    def phase_for(task):
        if task.phase_id:return phases.get(task.phase_id)
        module=modules.get(task.module_id)
        return phases.get(module.phase_id) if module and module.phase_id else None
    def group_for(task):
        if task.phase_id:return task.group_label or ''
        module=modules.get(task.module_id)
        return module.name if module else task.group_label or ''
    def label(check):
        if not check.vehicle_unit_id:return '任务级检查（未逐车核验）'
        unit=units.get(check.vehicle_unit_id)
        return (unit.fleet_no or unit.asset_code) if unit else '车辆来源待核对'
    matrices=step_states(db,[t for t in tasks if t.project_id and is_vehicle(t)])
    result={}
    for task in tasks:
        phase=phase_for(task)
        matrix=matrices.get(task.id)
        actor=actors.get(task.manual_completed_by) if task.manual_completed_by else None
        row={'id':task.id,'phase_id':phase.id if phase else None,'phase_name':stage_label(phase.name) if phase else '历史未分类',
            'group_label':group_for(task),'name':task.name,'description':task.description or '',
            'kind':'vehicle' if is_vehicle(task) else 'other','vehicle_step_key':task.vehicle_step_key,
            'applicable_vehicle_types':task.applicable_vehicle_types or [],'scope_conditions':task.scope_conditions or [],
            'is_completed':bool(matrix['complete']) if matrix else bool(task.manually_completed),'matrix':matrix,
            'completion':{'reason':task.manual_completed_reason or '', 'by':task.manual_completed_by,
                'by_name':actor.display_name if actor else '原操作人未记录' if task.manual_completed_by else '',
                'at':task.manual_completed_at.isoformat()+'Z' if task.manual_completed_at else None},
            'sort_order':task.sort_order or 0,'version':task.version or 0,'source_task_id':task.source_task_id,
            'source_vehicle_event_id':task.source_vehicle_event_id,'has_legacy_quantity':task.legacy_work_snapshot is not None or task.target_quantity is not None,
            'reference_docs':[{'filename':ref.get('filename'),'note':ref.get('note','')} for ref in task.reference_docs or []]}
        if not task.project_id:
            row['reference_docs']=[{'id':d.id,'filename':d.filename,'note':d.note} for d in template_docs[task.id]]
        if checks:
            row['quality_blocked']=task.id in blocked
            # Same shape as vehicle_checks.definition_data: frozen definitions, then unfrozen task-level sources.
            frozen=definitions[task.id]
            sources={d.source_check_id for d in frozen}
            row['check_definitions']=[{'source_check_id':d.source_check_id,'source_version':d.source_version,
                'name':d.name,'description':d.description or '','is_required':d.is_required,
                'is_safety_critical':d.is_safety_critical,'sort_order':d.sort_order} for d in frozen]+[
                {'source_check_id':c.id,'source_version':c.version or 0,'name':c.name,'description':c.description or '',
                 'is_required':c.is_required,'is_safety_critical':c.is_safety_critical,'sort_order':c.sort_order}
                for c in task_checks[task.id] if c.vehicle_unit_id is None and c.id not in sources]
            row['check_items']=[{'id':c.id,'name':c.name,'description':c.description or '',
                'vehicle_unit_id':c.vehicle_unit_id,'vehicle_step_key':c.vehicle_step_key,'vehicle_label':label(c),
                'is_safety_critical':c.is_safety_critical,'is_required':c.is_required,'is_applicable':c.is_applicable,
                'is_done':c.is_done,'failed':c.failed,'failed_reason':c.failed_reason,
                'not_applicable_reason':c.not_applicable_reason,'version':c.version or 0} for c in task_checks[task.id]]
        result[task.id]=row
    return result


def set_definition(db,task,data,*,creating=False):
    if any(data.get(k) is None for k in ('phase_id','description','group_label','sort_order') if k in data and not (creating and k=='sort_order')):raise HTTPException(400,'工作定义字段不能为空值')
    if 'name' in data and (not isinstance(data['name'],str) or not data['name'].strip()):raise HTTPException(400,'工作项名称不能为空白')
    if 'name' in data:data['name']=data['name'].strip()
    previous_phase=phase_of(db,task) if not creating else None
    if previous_phase is not None and previous_phase.name in REMINDER_ONLY_PHASE_NAMES:
        raise HTTPException(400,'历史准备工作来源只读，资料要求请到清单维护')
    if 'phase_id' in data:assert_phase(db,data['phase_id'],project_id=task.project_id,template_id=task.template_id);task.phase_id=data['phase_id']
    if creating:
        if 'sort_order' not in data or data['sort_order'] is None:
            task.sort_order=(db.query(func.max(Task.sort_order)).filter(Task.project_id==task.project_id,Task.template_id==task.template_id,Task.phase_id==task.phase_id).scalar() or 0)+1
        task.quantity_type='per_vehicle' if data['kind']=='vehicle' else 'fixed'
        task.target_quantity=None;task.unit='台' if is_vehicle(task) else '项'
    for key in ('name','description','group_label','sort_order','applicable_vehicle_types','scope_conditions'):
        if key in data and not (creating and key=='sort_order' and data[key] is None):setattr(task,key,data[key])
    if 'vehicle_step_key' in data or creating:
        from app.services.vehicle_checks import bind_step
        key=data.get('vehicle_step_key')
        if creating and is_vehicle(task) and not key:raise HTTPException(400,'车辆工作必须明确关联当前真实车辆环节')
        bind_step(db,task,key)
    if not is_vehicle(task) and task.vehicle_step_key:raise HTTPException(400,'非车辆工作不能关联车辆环节')
    if creating:
        db.add(task);db.flush()
        from app.services.vehicle_checks import import_definitions,generate_for_units
        checks=data.get('checks') or []
        if is_vehicle(task) and task.project_id:
            import_definitions(db,task,checks)
            generate_for_units(db,task.project_id,db.query(VehicleUnit).filter_by(project_id=task.project_id).all(),task)
        else:
            for index,check in enumerate(checks):db.add(CheckItem(task_id=task.id,project_id=task.project_id,
                name=check['name'],description=check.get('description',''),template_id=task.template_id,is_required=check.get('is_required',True),
                is_safety_critical=check.get('is_safety_critical',False),sort_order=index))
    db.flush()


def complete(db,project,user,task_id,data):
    from app.services import field_operations as actual
    capture_actual=not db.info.get('field_operation_active')
    if capture_actual:
        project=actual.authority(db,project.id,user)
        user=db.get(User,user.id)
        actual_before=actual.snapshot(db,project.id,'work',task_id)
        if actual_before.get('is_done') and data['is_completed']:
            actual.owner_guard(db,project,user,'work',task_id,'',actual_before)
    from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
    project=lock_writable_project(db,project,user);db.refresh(user)
    member=user.id in (project.members or []) or user.id in (project.manager,project.technical_manager) or C_PLAN in project_capabilities(user,project)
    if not has_permission(user,'worker.report',default=True) or not member:raise HTTPException(403,'仅有填报权限的项目成员可登记工作完成')
    if project.status not in EXECUTION_PROJECT_STATUSES:raise HTTPException(400,'现场实施前或项目结束后不能登记工作完成')
    task=lock_work(db,project,user,task_id,data['version'])
    phase=phase_of(db,task)
    if phase is None or phase.name in REMINDER_ONLY_PHASE_NAMES:raise HTTPException(400,'历史准备工作来源只读，资料请到清单维护')
    if is_vehicle(task):raise HTTPException(400,'车辆工作完成由真实车辆进度表登记，不能用工作完成状态覆盖')
    reason=data['reason'].strip()
    if not reason:raise HTTPException(400,'完成或重新打开工作必须填写理由')
    checks=db.query(CheckItem).filter_by(task_id=task.id).populate_existing().all()
    if data['is_completed']:
        safety=[c for c in checks if c.is_safety_critical and (not c.is_done or c.failed or not c.is_applicable)]
        pending=[c for c in checks if c.is_required and c.is_applicable and not c.is_done and not c.failed]
        if safety or pending:raise HTTPException(400,{'message':'必需检查尚未满足，不能完成工作','blockers':[{'id':c.id,'name':c.name} for c in safety+pending]})
        from app.services.manual_completion import failed_checks,snapshot
        failed=failed_checks(db,task.id)
        if failed:
            if C_PLAN not in project_capabilities(user,project) or not data.get('override_failed'):
                raise HTTPException(400,'存在普通失败检查，需负责人对当前失败版本明确确认覆盖')
            expected={item['id']:item['version'] for item in data.get('failed_checks',[])}
            if expected!={c.id:c.version or 0 for c in failed}:raise HTTPException(409,'失败检查版本或范围已变化，请刷新核对')
        task.manual_check_overrides=snapshot(failed)
    else:task.manual_check_overrides=[]
    old={'is_completed':bool(task.manually_completed),'reason':task.manual_completed_reason}
    task.manually_completed=data['is_completed'];task.manual_completed_by=user.id
    task.manual_completed_at=utcnow();task.manual_completed_role=user.role;task.manual_completed_reason=reason
    log_change(db,project.id,'task',task.id,'complete' if data['is_completed'] else 'reopen',user.id,
        f"{'完成' if data['is_completed'] else '重新打开'}工作「{task.name}」；{reason}",old,
        {'is_completed':data['is_completed'],'reason':reason,'ordinary_check_overrides':task.manual_check_overrides})
    db.flush()
    if capture_actual:
        from app.time_utils import project_today
        actual.capture(db,project,user,'work',task_id,'',actual_before,project_today(project.timezone),note=reason)
    return task


def selected_template_work(db,template_id,selection,excluded_ids=None,excluded_names=None):
    """Canonical task IDs; old module IDs are a read-only import adapter."""
    tid=None if template_id=='default' else template_id
    tasks=db.query(Task).filter(Task.project_id.is_(None),Task.template_id==tid).all()
    valid={t.id:t for t in tasks}
    modules={m.id for m in db.query(Module).filter(Module.project_id.is_(None),Module.template_id==tid)}
    unknown=set(selection)-set(valid)-modules
    if unknown:raise ValueError('工作范围已失效，请重新读取模板')
    ids={t.id for t in tasks if t.id in selection or t.module_id in selection}
    if set(excluded_ids or [])-ids:raise ValueError('排除的工作项不在所选范围')
    return [t for t in tasks if t.id in ids and t.id not in (excluded_ids or []) and t.name not in (excluded_names or [])
            and phase_of(db,t) is not None and phase_of(db,t).name not in REMINDER_ONLY_PHASE_NAMES]


def generate(db,project,source_tasks):
    """Freeze independent stage/work/check definitions without creating Modules."""
    from app.services.generate_tasks import copy_reference_docs
    from app.services.vehicle_checks import definition_data,import_definitions,generate_for_units
    # check_items：本次实际生成的检查记录；check_definitions：冻结的检查要求（按车辆的在车辆建档后逐车生成）。
    result={'tasks':0,'check_items':0,'check_definitions':0,'vehicle_check_definitions':0,'modules':[],'work_items':[]}
    mapping={t.source_task_id:t for t in db.query(Task).filter_by(project_id=project.id) if t.source_task_id}
    for source in source_tasks:
        if source.id in mapping:continue
        origin=phase_of(db,source)
        phase=db.query(Phase).filter(Phase.project_id==project.id,Phase.name.in_([origin.name,stage_label(origin.name)])).order_by(Phase.sort_order,Phase.id).first()
        if phase is None:
            phase=Phase(project_id=project.id,name=stage_label(origin.name),color=origin.color,sort_order=origin.sort_order,
                entry_criteria=origin.entry_criteria,exit_criteria=origin.exit_criteria)
            db.add(phase);db.flush()
        row=Task(project_id=project.id,phase_id=phase.id,module_id=None,name=source.name,description=source.description,
            quantity_type='per_vehicle' if is_vehicle(source) else 'fixed',target_quantity=None,
            unit='台' if is_vehicle(source) else '项',safety_flag=source.safety_flag,
            applicable_vehicle_types=list(source.applicable_vehicle_types or []),group_label=group_of(db,source),
            scope_conditions=list(source.scope_conditions or []),sort_order=source.sort_order,
            source_task_id=source.id,vehicle_step_key=source.vehicle_step_key,
            legacy_work_snapshot={'kind':'template_definition_source','source_task_id':source.id,
                'quantity':{'type':source.quantity_type,'target':source.target_quantity,'unit':source.unit},
                'original':source.legacy_work_snapshot})
        db.add(row);db.flush();copy_reference_docs(db,source,row)
        definitions=definition_data(db,source)
        result['check_definitions']+=len(definitions)
        if is_vehicle(row):
            result['vehicle_check_definitions']+=len(definitions)
            import_definitions(db,row,definitions)
            result['check_items']+=len(generate_for_units(db,project.id,db.query(VehicleUnit).filter_by(project_id=project.id).all(),row))
        else:
            for i,value in enumerate(definitions):
                db.add(CheckItem(project_id=project.id,task_id=row.id,name=value['name'],description=value.get('description',''),
                    is_required=value.get('is_required',True),is_safety_critical=value.get('is_safety_critical',False),sort_order=i))
                result['check_items']+=1
        mapping[source.id]=row;result['tasks']+=1;result['work_items'].append(row.id)
    for source in source_tasks:
        target=mapping.get(source.id)
        if target and target.id in result['work_items']:
            target.depends_on=[mapping[key].id for key in source.depends_on or [] if key in mapping]
    db.flush()
    return result


def portable_definition(db,task):
    """Definitions only. Source qualification stays in execution_evidence."""
    from app.services.vehicle_checks import definition_data
    return {'source_id':task.id,'source_task_id':task.source_task_id,'name':task.name,'description':task.description or '',
        'kind':'vehicle' if is_vehicle(task) else 'other','quantity_type':task.quantity_type,
        'target_quantity':task.target_quantity,'unit':task.unit,'standard_hours':task.standard_hours,
        'safety_flag':task.safety_flag,'applicable_vehicle_types':task.applicable_vehicle_types or [],
        'vehicle_step_key':task.vehicle_step_key,'group_label':group_of(db,task),'scope_conditions':task.scope_conditions or [],
        'depends_on':task.depends_on or [],'sort_order':task.sort_order or 0,
        'legacy_work_snapshot':task.legacy_work_snapshot,'check_items':definition_data(db,task)}


def portable_modules(db,project_id):
    """Legacy JSON envelopes carry labels; no Module business identity is needed."""
    groups={};retired=[]
    for task in db.query(Task).filter_by(project_id=project_id).order_by(Task.sort_order,Task.id):
        phase=phase_of(db,task)
        if phase and phase.name in REMINDER_ONLY_PHASE_NAMES:
            retired.append({'read_only':True,'phase_name':phase.name,**portable_definition(db,task)});continue
        label=group_of(db,task);key=(phase.id if phase else None,label)
        envelope=groups.setdefault(key,{'name':label or '工作项','source_group_label':label,'read_only_source_envelope':True,
            'phase_name':phase.name if phase else '历史未分类','phase_color':phase.color if phase else '#1890ff',
            'phase_sort_order':phase.sort_order if phase else 0,'phase_entry_criteria':phase.entry_criteria if phase else '',
            'phase_exit_criteria':phase.exit_criteria if phase else '', 'category':'core','is_selected':True,
            'sort_order':task.sort_order or 0,'preparation_conditions':task.scope_conditions or [],'tasks':[]})
        envelope['tasks'].append(portable_definition(db,task))
    return list(groups.values()),retired
