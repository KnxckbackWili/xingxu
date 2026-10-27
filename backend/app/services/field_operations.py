"""Actual field facts and append-only corrections; plans never imply execution."""
import hashlib,json,os,uuid
from datetime import date,timedelta
from fastapi import HTTPException
from sqlalchemy import func
from app.models import User,Project,Task,CheckItem,VehicleProgress,FieldOperation
from app.services.scope import ensure_project_visible
from app.services.record_lock import lock_writable_project,lock_record
from app.services.system_permissions import has_permission
from app.services.permissions import C_PLAN,project_capabilities
from app.services.change_log import log_change
from app.time_utils import project_today,utcnow


def date_window(project):
    today=project_today(project.timezone)
    configured=os.getenv('FIELD_BACKFILL_DAYS','').strip()
    try:days=max(1,min(90,int(configured))) if configured else None
    except ValueError:raise HTTPException(503,'补记窗口配置无效，请联系管理员')
    earliest=today-timedelta(days=days-1) if days else today-timedelta(days=today.weekday()+7)
    return {'earliest':earliest.isoformat(),'latest':today.isoformat(),'timezone':project.timezone}


def validate_date(project,value):
    bounds=date_window(project)
    if not bounds['earliest']<=value.isoformat()<=bounds['latest']:
        raise HTTPException(400,'完成日期必须在项目当地补记窗口内，且不能晚于当地今天')


def authority(db,project_id,user,assisted=None):
    from app.services.two_factor import required
    was_required=required(user)
    version=user.token_version or 0
    user=db.get(User,user.id)
    if user is None:raise HTTPException(401,'账号不存在')
    project=ensure_project_visible(db,project_id,user)
    project=lock_writable_project(db,project,user)
    anchor=db.query(User).filter_by(username='admin').first() or db.query(User).order_by(User.id).first()
    if anchor:lock_record(db,anchor,conflict_detail='账号授权正在变化，请稍后重试')
    for identity in sorted({identity for identity in (user.id,assisted) if identity and (anchor is None or identity!=anchor.id)}):
        person=db.get(User,identity)
        if person:lock_record(db,person,conflict_detail='实际操作人员正在变化，请稍后重试')
    db.refresh(user)
    if not user.is_active or (user.token_version or 0)!=version:raise HTTPException(401,'账号或会话已变化，请重新登录')
    if required(user) and (not was_required or not user.mfa_enabled):raise HTTPException(401,'账号验证要求已变化，请重新登录')
    if user.role in ('readonly','external') or not has_permission(user,'worker.report',default=True):raise HTTPException(403,'没有现场登记权限')
    member=user.id in (project.members or []) or user.id in (project.manager,project.technical_manager)
    if not member and C_PLAN not in project_capabilities(user,project):raise HTTPException(403,'仅当前项目成员可登记现场事实')
    return project


def latest(db,project_id,kind,target_id,step_key=''):
    return db.query(FieldOperation).filter_by(project_id=project_id,kind=kind,target_id=target_id,step_key=step_key).order_by(FieldOperation.sequence.desc(),FieldOperation.id.desc()).first()


def snapshot(db,project_id,kind,target_id,step_key=''):
    if kind=='vehicle':
        row=db.query(VehicleProgress).filter_by(project_id=project_id,vehicle_unit_id=target_id,step_key=step_key).first()
        return {'version':row.version if row else 0,'is_done':bool(row and row.is_done),
                'done_on':row.done_on.isoformat() if row and row.done_on else None,'done_by':row.done_by if row else None,
                'note':row.note if row else ''}
    if kind=='work':
        row=db.get(Task,target_id,populate_existing=True)
        if row is None or row.project_id!=project_id:raise HTTPException(404,'工作项不存在')
        return {'version':row.version or 0,'is_done':bool(row.manually_completed),'done_by':row.manual_completed_by,'note':row.manual_completed_reason or ''}
    row=db.get(CheckItem,target_id,populate_existing=True)
    task=db.get(Task,row.task_id) if row else None
    if not row or not task or task.project_id!=project_id:raise HTTPException(404,'检查项不存在')
    return {'version':row.version or 0,'is_done':bool(row.is_done),'done_by':row.done_by,
            'failed':bool(row.failed),'failed_reason':row.failed_reason or '',
            'is_applicable':bool(row.is_applicable),'not_applicable_reason':row.not_applicable_reason or ''}


def owner_guard(db,project,user,kind,target,step,before):
    if C_PLAN in project_capabilities(user,project):return
    previous=latest(db,project.id,kind,target,step)
    if not before.get('is_done') and not before.get('failed') and before.get('is_applicable',True):return
    actor=previous.actor_id if previous else before.get('done_by')
    if actor and actor!=user.id:raise HTTPException(403,'他人的实际记录不能修改或撤回；请明确选择协助登记或联系负责人')
    if previous:validate_date(project,previous.completion_date)
    elif before.get('is_done') and not actor:raise HTTPException(403,'历史记录无法确认本人身份，请联系负责人核对')


def capture(db,project,user,kind,target,step,before,completion_date,*,note='',assisted=None,cell=None,client_uuid=None,payload_hash=None,action='record',replaces=None,root=None,restores=None,reason=''):
    db.flush()  # SessionLocal deliberately disables autoflush; snapshot must see the mutation.
    after=snapshot(db,project.id,kind,target,step)
    label_row=db.get(Task,target) if kind=='work' else db.get(CheckItem,target) if kind=='check' else None
    label=label_row.name if label_row else step
    if kind=='vehicle' or kind=='check' and label_row and label_row.vehicle_unit_id:
        from app.models import VehicleUnit
        unit=db.get(VehicleUnit,target if kind=='vehicle' else label_row.vehicle_unit_id)
        if kind=='vehicle':
            from app.services.vehicle_progress import project_steps
            label=next((row.name for row in project_steps(db,project.id) if row.key==step),step)
        if unit:label=(unit.fleet_no or unit.asset_code)+' · '+label
    sequence=(db.query(func.max(FieldOperation.sequence)).filter_by(project_id=project.id).scalar() or 0)+1
    row=FieldOperation(project_id=project.id,kind=kind,target_id=target,step_key=step,weekly_cell_id=cell,target_label=label,
        actor_id=user.id,assisted_user_id=assisted,completion_date=completion_date,is_done=after['is_done'],
        note=note,action=action,replaces_id=replaces,root_id=root,restores_id=restores,reason=reason or note,
        before_state=before,after_version=after['version'],sequence=sequence,
        client_uuid=client_uuid or str(uuid.uuid4()),payload_hash=payload_hash or '')
    db.add(row);db.flush()
    log_change(db,project.id,'field_operation',row.id,action,user.id,'登记现场实际操作（协助）' if assisted else '登记现场实际操作',
        before,{'kind':kind,'target_id':target,'step_key':step,'completion_date':completion_date.isoformat(),
                'recorded_at':row.recorded_at.isoformat(),'actor_id':user.id,'assisted_user_id':assisted,
                'is_done':row.is_done,'note':note,'reason':row.reason,'replaces_id':replaces,'restores_id':restores})
    return row


def text_redactor(db,project,user):
    from app.models import ProjectDocument,ProjectDocumentDefinition,Attachment
    from app.services.project_documents import can_read_document,can_read_definition,can_read_file
    names=set()
    for model,can_read in ((ProjectDocument,can_read_document),(ProjectDocumentDefinition,can_read_definition)):
        names.update(row.name for row in db.query(model).filter_by(project_id=project.id) if row.name and not can_read(user,project,row))
    names.update(row.filename for row in db.query(Attachment).filter_by(project_id=project.id) if row.filename and not can_read_file(user,project,row))
    def redact(value):
        for name in sorted(names,key=len,reverse=True):value=value.replace(name,'受限资料（请负责人核对）')
        return value
    return redact


def serialize(db,row,user,*,text_filter=None):
    project=db.get(Project,row.project_id)
    current=latest(db,row.project_id,row.kind,row.target_id,row.step_key)
    try:actual=snapshot(db,row.project_id,row.kind,row.target_id,row.step_key)
    except HTTPException:actual={'version':-1}
    bounds=date_window(project)
    from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
    editable=(project.status in EXECUTION_PROJECT_STATUSES and has_permission(user,'worker.report',default=True) and row.actor_id==user.id and current.id==row.id and row.after_version==actual['version'] and
              bounds['earliest']<=row.completion_date.isoformat()<=bounds['latest'] and (row.action!='retract' or row.restores_id is not None))
    actor=db.get(User,row.actor_id) if row.actor_id else None
    assisted=db.get(User,row.assisted_user_id) if row.assisted_user_id else None
    text_filter=text_filter or text_redactor(db,project,user)
    label=text_filter(row.target_label)
    return {'id':row.id,'project_id':row.project_id,'project_name':project.name,'kind':row.kind,'target_id':row.target_id,
            'step_key':row.step_key,'target_name':label,'weekly_cell_id':row.weekly_cell_id,'actor_id':row.actor_id,
            'actor_name':actor.display_name if actor else '历史账号','assisted_user_id':row.assisted_user_id,
            'assisted_user_name':assisted.display_name if assisted else None,'completion_date':row.completion_date.isoformat(),
            'recorded_at':row.recorded_at.isoformat()+'Z','is_done':row.is_done,'note':text_filter(row.note),'action':row.action,
            'replaces_id':row.replaces_id,'restores_id':row.restores_id,'root_id':row.root_id or row.id,
            'operation_reason':text_filter(row.reason),'effective':row.action!='retract' or row.restores_id is not None,
            'version':row.after_version,'can_edit':editable,'can_retract':editable and row.action!='retract',**bounds}


def _assignment(db,project,user,data):
    assisted=data.get('assisted_user_id')
    if assisted:
        person=db.get(User,assisted,populate_existing=True)
        if assisted==user.id or not person or not person.is_active or (assisted not in (project.members or []) and assisted not in (project.manager,project.technical_manager)):
            raise HTTPException(400,'被协助人必须是当前启用的项目成员，且不能是自己')
    cell_id=data.get('weekly_cell_id')
    if not cell_id:return
    from app.models import WeeklyPlanCell
    cell=db.get(WeeklyPlanCell,cell_id,populate_existing=True)
    if not cell or cell.project_id!=project.id or not cell.published or getattr(cell,'is_cancelled',False):raise HTTPException(404,'已发布周计划不存在')
    assignees=cell.assignee_ids or []
    if not assignees:raise HTTPException(409,'此工作尚未分配，请先使用认领按钮')
    if (assisted or user.id) not in assignees:raise HTTPException(403,'实际记录与当前周计划负责人不匹配')
    task_id=data['target_id'] if data['kind']=='work' else db.get(CheckItem,data['target_id']).task_id if data['kind']=='check' and db.get(CheckItem,data['target_id']) else None
    if task_id and task_id!=cell.task_id:raise HTTPException(404,'工作不属于该周计划')
    task=db.get(Task,cell.task_id)
    check=db.get(CheckItem,data['target_id']) if data['kind']=='check' else None
    unit_id=data['target_id'] if data['kind']=='vehicle' else check.vehicle_unit_id if check else None
    if data['kind']=='vehicle' or unit_id:
        from app.services.vehicle_progress import project_steps
        step_key=data.get('step_key') if data['kind']=='vehicle' else task.vehicle_step_key if task else None
        step=next((step for step in project_steps(db,project.id) if step.key==step_key),None)
        if not step or not task or (step.source_task_id!=task.id and getattr(task,'vehicle_step_key',None)!=step.key):
            raise HTTPException(404,'车辆环节不属于该周计划')
        if getattr(cell,'vehicle_step_key',None) and cell.vehicle_step_key!=step.key:raise HTTPException(409,'周计划环节与当前工作不一致，请负责人核对')
        scope=cell.scope or {}
        if scope.get('vehicle_unit_ids') and unit_id not in scope['vehicle_unit_ids']:raise HTTPException(404,'车辆不属于该计划批次')
        if scope.get('vehicle_type'):
            from app.models import VehicleUnit,Vehicle
            unit=db.get(VehicleUnit,unit_id)
            vehicle=db.get(Vehicle,unit.vehicle_id) if unit and unit.vehicle_id else None
            if not vehicle or vehicle.vehicle_type!=scope['vehicle_type']:raise HTTPException(404,'车辆不属于该计划车型')


def apply(db,project_id,user,data,*,record_id=None,retract=False):
    project=authority(db,project_id,user,data.get('assisted_user_id'))
    user=db.get(User,user.id)
    if not data['reason'].strip():raise HTTPException(400,'请填写明确的实际情况或操作理由')
    digest=hashlib.sha256(json.dumps({'data':data,'record_id':record_id,'retract':retract},sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    repeated=db.query(FieldOperation).filter_by(project_id=project_id,actor_id=user.id,client_uuid=data['client_uuid']).first()
    if repeated:
        if repeated.payload_hash!=digest:raise HTTPException(409,'该操作编号已绑定其它原始内容，不能改写后重试')
        return repeated
    kind,target,step=data['kind'],data['target_id'],data.get('step_key') or ''
    before=snapshot(db,project_id,kind,target,step)
    completion_date=data['completion_date'];validate_date(project,completion_date)
    old=None;restores=None;restored_record=None
    if record_id:
        old=db.get(FieldOperation,record_id)
        if not old or old.project_id!=project_id or old.actor_id!=user.id:raise HTTPException(404,'本人记录不存在')
        if (old.kind,old.target_id,old.step_key)!=(kind,target,step):raise HTTPException(400,'修订不能更换原记录对象')
        eligibility=serialize(db,old,user)
        if not eligibility['can_retract' if retract else 'can_edit']:raise HTTPException(409,'记录超出补记窗口或已被后续操作改变，不能覆盖')
        if data['version']!=old.after_version:raise HTTPException(409,'记录版本已变化')
        if retract:
            data={**data,**{k:v for k,v in old.before_state.items() if k not in ('version','done_by')},'reason':data['reason']}
            restores=old.replaces_id if old.action=='edit' else None
            restored_record=db.get(FieldOperation,restores) if restores else None
            if restored_record and (restored_record.root_id or restored_record.id)!=(old.root_id or old.id):
                raise HTTPException(409,'修订来源链不一致，未恢复当前事实')
            completion_date=restored_record.completion_date if restored_record else old.completion_date
            if kind=='vehicle' and data['is_done'] and old.before_state.get('done_on'):
                completion_date=date.fromisoformat(old.before_state['done_on'])
        elif kind=='check':
            # A date/note correction owns no new inspection decision. Preserve
            # the full locked tri-state; is_done=False alone would clear failure.
            data={**data,**{key:before[key] for key in ('is_done','failed','failed_reason','is_applicable','not_applicable_reason')}}
    elif before.get('is_done') and data['is_done']:owner_guard(db,project,user,kind,target,step,before)
    if not record_id:_assignment(db,project,user,data)
    if before['version']!=data['version']:raise HTTPException(409,'当前事实已改变，请保留原操作并刷新核对')
    record_note=(restored_record.note if restored_record else old.before_state.get('note','')) if retract else data.get('note','') if old else data.get('note') or data['reason']
    if kind=='work':
        from app.services.work_items import complete
        if record_id and before['is_done']==data['is_done']:
            # Correcting annotation/date grants no completion qualification and
            # must not discard a previously acknowledged failed-check snapshot.
            from app.services.work_items import lock_work
            from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
            if project.status not in EXECUTION_PROJECT_STATUSES:raise HTTPException(400,'项目当前状态不允许修订现场记录')
            task=lock_work(db,project,user,target,data['version'])
            previous_note=task.manual_completed_reason
            task.manual_completed_reason=old.before_state.get('note','') if retract else data.get('note','')
            log_change(db,project.id,'task',task.id,'annotation',user.id,'修订本人实际记录的日期或附注',
                {'reason':previous_note},{'reason':task.manual_completed_reason,'revision_reason':data['reason']})
        else:
            previous_context=db.info.get('field_operation_active')
            db.info['field_operation_active']=True
            try:
                complete(db,project,user,target,{'version':data['version'],'is_completed':data['is_done'],'reason':data['reason'],
                    'override_failed':False,'failed_checks':[]})
            finally:
                if previous_context is None:db.info.pop('field_operation_active',None)
                else:db.info['field_operation_active']=previous_context
    elif kind=='vehicle':
        from app.routers.vehicle_progress import _apply_matrix,MatrixChange
        _apply_matrix(project_id,MatrixChange(cells=[{'vehicle_unit_id':target,'step_key':step,'version':data['version']}],
            is_done=data['is_done'],done_on=completion_date if data['is_done'] else None,reason=data['reason'],note=record_note),user,db)
    else:
        from app.routers.tasks import _apply_check,CheckItemUpdate
        fields={key:data[key] for key in ('failed','failed_reason','is_applicable','not_applicable_reason') if key in data}
        _apply_check(project_id,target,CheckItemUpdate(version=data['version'],is_done=data['is_done'],**fields),user,db)
    return capture(db,project,user,kind,target,step,before,completion_date,note=record_note,
        assisted=data.get('assisted_user_id'),cell=data.get('weekly_cell_id'),client_uuid=data['client_uuid'],payload_hash=digest,
        action='retract' if retract else 'edit' if old else 'record',replaces=record_id,
        root=(old.root_id or old.id) if old else None,restores=restores,reason=data['reason'])


def direct_matrix(db,project_id,user,body):
    project=authority(db,project_id,user)
    user=db.get(User,user.id)
    when=body.done_on or project_today(project.timezone)
    validate_date(project,when)
    previous=[]
    for cell in body.cells:
        before=snapshot(db,project_id,'vehicle',cell.vehicle_unit_id,cell.step_key)
        if before.get('is_done') and body.is_done:owner_guard(db,project,user,'vehicle',cell.vehicle_unit_id,cell.step_key,before)
        previous.append((cell,before))
    from app.routers.vehicle_progress import _apply_matrix
    result=_apply_matrix(project_id,body,user,db)
    for cell,before in previous:
        if snapshot(db,project_id,'vehicle',cell.vehicle_unit_id,cell.step_key)['version']!=before['version']:
            capture(db,project,user,'vehicle',cell.vehicle_unit_id,cell.step_key,before,when,note=body.note or body.reason,reason=body.reason)
    db.commit();return result


def direct_check(db,project_id,target,user,body):
    project=authority(db,project_id,user)
    user=db.get(User,user.id)
    before=snapshot(db,project_id,'check',target)
    from app.routers.tasks import _apply_check
    result=_apply_check(project_id,target,body,user,db)
    capture(db,project,user,'check',target,'',before,project_today(project.timezone),note=body.failed_reason or body.not_applicable_reason or '')
    db.commit();return result


def export_evidence(db,project,user):
    if user is None:raise ValueError('实际操作便携导出必须提供当前账号；完整恢复使用私有加密快照')
    ensure_project_visible(db,project.id,user)
    from app.services.project_retention import _row
    redact=text_redactor(db,project,user)
    def filtered(value):
        if isinstance(value,str):return redact(value)
        if isinstance(value,dict):return {key:filtered(item) for key,item in value.items()}
        if isinstance(value,list):return [filtered(item) for item in value]
        return value
    return {'read_only':True,'verified':False,'meaning':'原始实际操作仅供核对，导入不继承完成资格或操作身份。',
        'records':[filtered(_row(row)) for row in db.query(FieldOperation).filter_by(project_id=project.id).order_by(FieldOperation.sequence)]}


def effective_records(rows):
    by_root={}
    for row in rows:
        root=row.root_id or row.id
        if root not in by_root or row.sequence>by_root[root].sequence:by_root[root]=row
    return [row for row in by_root.values() if row.action!='retract' or row.restores_id is not None]
