"""Project-owned document rules, real evidence submission and immutable versions.

Callers own a single project lock and transaction. Template edits never rewrite a
project's snapshots; event/period tasks instantiate only through this module.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session, object_session
from sqlalchemy import or_

from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE
from app.models import (Project, User, Task, Issue, Attachment, DocumentRequirement, DocumentTemplateFile,
    ProjectDocumentDefinition, ProjectDocument, DocumentVersion, VehicleUnit, ProjectEvent)
from app.services.change_log import log_change
from app.services.permissions import project_capabilities, authorize_project, C_PLAN
from app.services.system_permissions import has_permission
from app.services.record_lock import lock_writable_project
from app.services.scope import ensure_project_visible
from app.services.optimistic import bump_version
from app.services.document_requirements import RequirementInput, track_new_file, read_asset
from app.time_utils import utcnow

RULE_FIELDS = ('stage_key','code','name','template_no','required','scope','platform','timing_type','timing_event',
    'timing_offset_hours','timing_weekday','trigger_type','blank_file_id','sort_order','note','source_metadata')
DEFAULT_FIELDS = ('confidential_default','external_visible_default','external_never_visible')
DEFERRED_TYPES = {'weekly','on_trigger'}
IDENTITY_FIELDS = ('scope','platform','timing_type','timing_event','timing_weekday','trigger_type')


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if isinstance(value,datetime) else value.isoformat() if value else None


def applicable(project, rule):
    return not rule.platform or rule.platform == project.dispatch_platform


def can_submit(user, project):
    return _internal_actor(user) and has_permission(user, 'worker.deliver', default=True) and (user.role == 'admin' or user.id in {project.manager, project.technical_manager, *(project.members or [])})


def writable(db, project_id, user, capability):
    authorized_version=user.token_version or 0
    project = lock_writable_project(db, ensure_project_visible(db, project_id, user), user)
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401,'账号已停用，请重新登录')
    if (user.token_version or 0)!=authorized_version:
        raise HTTPException(401,'账号或会话已变化，请重新登录')
    project = ensure_project_visible(db, project_id, user)
    if capability == 'worker.deliver':
        if not can_submit(user,project):
            raise HTTPException(403,'仅有资料提交权限的项目成员可操作')
    else:
        authorize_project(user,project,capability)
    return project


def _internal_actor(user):
    return user is not None and getattr(user, 'is_active', True) is not False and user.role != 'external'


def _active_actor(user):
    return user is not None and getattr(user,'is_active',True) is not False


def _in_confidential_scope(user, project, row):
    # Project ownership is manager, not a global role, uploader or technical role.
    return _internal_actor(user) and (user.id == project.manager or user.id in (getattr(row,'confidential_user_ids',None) or []))


def can_read_document(user, project, document):
    if document.project_id!=project.id:return False
    if not _active_actor(user):return False
    if user.role=='external':return not document.confidential and not document.external_never_visible
    return not document.confidential or _in_confidential_scope(user, project, document)


def can_read_definition(user, project, definition):
    if definition.project_id!=project.id:return False
    if not _active_actor(user):return False
    if user.role=='external':return not definition.confidential_default and not definition.external_never_visible
    return not definition.confidential_default or _in_confidential_scope(user, project, definition)


def _file_documents(asset):
    db = object_session(asset)
    if db is None:
        return []
    # A second Attachment record sharing the same original must not be a bypass.
    aliases = db.query(Attachment.id).filter(Attachment.stored_name == asset.stored_name)
    return db.query(ProjectDocument).join(DocumentVersion, DocumentVersion.project_document_id == ProjectDocument.id).filter(
        DocumentVersion.attachment_id.in_(aliases)).populate_existing().all()


def file_is_confidential(asset):
    return bool(asset.confidential or any(row.confidential for row in _file_documents(asset)))


def can_read_file(user, project, asset, *, _references=None):
    """The intersection of an explicit file policy and every confidential use."""
    if not _active_actor(user) or asset.project_id!=project.id:
        return False
    references = _file_documents(asset) if _references is None else _references
    private = [row for row in references if row.confidential]
    explicit = asset.confidential_explicit or (asset.confidential and not private)
    if user.role=='external' and (explicit or private or asset.confidential or any(row.external_never_visible for row in references)):
        return False
    if explicit and not _in_confidential_scope(user, project, asset):
        return False
    db = object_session(asset)
    for document in private:
        owner = project if document.project_id == project.id else db.get(Project, document.project_id)
        if owner is None or not can_read_document(user, owner, document):
            return False
        if owner.id != project.id:
            from app.services.scope import visible_project_ids
            if owner.id not in visible_project_ids(db, user):
                return False
    return True


def can_read_blank(db, user, asset, project):
    """Project blank copies follow every private family in this project.

    Global unfilled template assets remain public template resources.
    """
    if not _internal_actor(user):
        return False
    for model, predicate in ((ProjectDocumentDefinition, can_read_definition), (ProjectDocument, can_read_document)):
        query=db.query(model).filter_by(blank_file_id=asset.id,project_id=project.id)
        for row in query.populate_existing():
            owner = db.get(Project, row.project_id)
            if owner is None or not predicate(user, owner, row):
                return False
    return True


def redact_document_text(db, project, actor, text, *, public_names=()):
    """Text at an authorized response/notification boundary, using the same ACL."""
    private=[]
    for model,predicate in ((ProjectDocument,can_read_document),(ProjectDocumentDefinition,can_read_definition)):
        for row in db.query(model).filter_by(project_id=project.id).populate_existing():
            if not predicate(actor,project,row) and row.name not in public_names:
                private.extend([row.name,f'{row.code} {row.name}'])
    result=text
    for value in sorted(set(value for value in private if value),key=len,reverse=True):
        result=result.replace(value,'受限资料（请负责人核对）')
    return result


def filter_blockers(db, project, actor, blockers):
    """Preserve real blockers while hiding confidential titles from their caller.

    check_transition remains actor-free and pure; run this only at the response
    boundary. It also accepts dictionaries for future notification adapters.
    """
    from dataclasses import replace
    restricted=[]
    for model,predicate in ((ProjectDocument,can_read_document),(ProjectDocumentDefinition,can_read_definition)):
        restricted.extend(row for row in db.query(model).filter_by(project_id=project.id).populate_existing() if not predicate(actor,project,row))
    if not restricted:return list(blockers)
    result=[]
    signatures={'到货签收单','调试完工单','上线运行单','培训记录表'}
    for blocker in blockers:
        kind=blocker.get('type') if isinstance(blocker,dict) else blocker.type
        message=blocker.get('message','') if isinstance(blocker,dict) else blocker.message
        contains_private=any((row.name and row.name in message) or (not row.name and row.code and row.code in message) for row in restricted)
        if kind in {'documents','kickoff_documents'} and contains_private:
            message='仍有必需资料需要项目负责人核对，请联系负责人处理'
        else:
            message=redact_document_text(db,project,actor,message,public_names=signatures if kind=='signature_documents' else ())
        result.append({**blocker,'message':message} if isinstance(blocker,dict) else replace(blocker,message=message))
    return result


def audit_access(db, project, user, *, documents=(), definitions=(), files=(), action='confidential_view'):
    """Audit actual authorized responses, never predicate evaluation or secrets."""
    verb={'confidential_dl':'下载','confidential_export':'导出'}.get(action,'查看')
    for row in {row.id: row for row in documents}.values():
        if row.confidential:
            if not can_read_document(user, project, row):raise HTTPException(403, '保密资料权限已变化')
            log_change(db, project.id, 'project_document', row.id, action, user.id, verb+'已授权保密资料')
    for row in {row.id: row for row in definitions}.values():
        if row.confidential_default:
            if not can_read_definition(user, project, row):raise HTTPException(403, '保密资料要求权限已变化')
            log_change(db, project.id, 'project_document_definition', row.id, action, user.id, verb+'已授权保密资料要求')
    for row in {row.id: row for row in files}.values():
        if file_is_confidential(row):
            if not can_read_file(user, project, row):raise HTTPException(403, '保密文件权限已变化')
            log_change(db, project.id, 'attachment', row.id, action, user.id, verb+'已授权保密文件')


def confidentiality_members(db, project):
    from app.services.scope import visible_project_ids
    return [row for row in db.query(User).filter_by(is_active=True).order_by(User.display_name, User.id)
            if row.role != 'external' and project.id in visible_project_ids(db, row)]


def _validate_confidential_scope(db, project, user, user_ids):
    if not _internal_actor(user) or user.id != project.manager:
        raise HTTPException(403, '仅项目负责人可设置保密范围，其他角色不能自行授权')
    authorize_project(user,project,C_PLAN)
    if (not isinstance(user_ids,(list,tuple)) or len(user_ids)>200 or any(not isinstance(value,str) or not value.strip() or len(value)>36 for value in user_ids)
            or len(set(user_ids))!=len(user_ids)):
        raise HTTPException(400,'指定人员必须是最多200个不同的有效账号ID')
    from app.services.scope import visible_project_ids
    selected=db.query(User).filter(User.id.in_(user_ids)).populate_existing().all() if user_ids else []
    if len(selected)!=len(user_ids) or any(not member.is_active or member.role=='external' or project.id not in visible_project_ids(db,member) for member in selected):
        raise HTTPException(400, '指定人员须为有项目查看权限的启用内部账号')
    return sorted(set(user_ids)-{project.manager})


def validate_upload_policy(db, project, user, *, confidential=False, user_ids=()):
    """Pure T25 seam; call after writable() on start/chunk/status/finish.

    Ordinary members may submit into an already-authorized private family, but
    only the current owner with C_PLAN may create an independent file policy.
    """
    if not isinstance(confidential,bool):raise HTTPException(400,'保密属性必须是布尔值')
    if not isinstance(user_ids,(list,tuple)):raise HTTPException(400,'附件可见人员必须是数组')
    if not confidential:
        if user_ids:raise HTTPException(400,'指定附件可见人员前须启用附件保密')
        return []
    return _validate_confidential_scope(db,project,user,user_ids)


def apply_upload_confidentiality(db, project, user, asset, *, confidential=False, user_ids=()):
    """Set a new file's independent policy before its first transaction commits."""
    selected=validate_upload_policy(db,project,user,confidential=confidential,user_ids=user_ids)
    if confidential:
        if asset.project_id!=project.id or object_session(asset) is not db:raise HTTPException(400,'附件必须属于当前项目和事务')
        db.flush()
        if asset.access_version!=1:raise HTTPException(409,'上传元数据不能覆盖既有附件保密范围')
        change_confidentiality(db,project,user,asset,confidential=True,user_ids=selected,expected=asset.access_version)
    return asset


def change_confidentiality(db, project, user, row, *, confidential, user_ids, expected):
    user_ids=_validate_confidential_scope(db,project,user,user_ids)
    flag = 'confidential_default' if isinstance(row, ProjectDocumentDefinition) else 'confidential'
    before = {'confidential': getattr(row, flag), 'confidential_user_ids': list(row.confidential_user_ids or []),
              'version':row.version if isinstance(row,ProjectDocument) else row.access_version}
    family = ((owned_definition(db, project.id, row.definition_id) if row.definition_id else None)
              if isinstance(row, ProjectDocument) else row if isinstance(row, ProjectDocumentDefinition) else None)
    instances = (db.query(ProjectDocument).filter_by(project_id=project.id, definition_id=family.id).populate_existing().all()
                 if family else [row] if isinstance(row, ProjectDocument) else [])

    def advance(target, version):
        if isinstance(target, ProjectDocument):
            bump_version(target, version, db=db)
            return
        from sqlalchemy import update
        changed = db.execute(update(type(target)).where(type(target).id == target.id, type(target).access_version == version)
            .values(access_version=version + 1).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise HTTPException(409, '保密范围已被其他操作修改，请刷新后重试')
        target.access_version = version + 1

    advance(row, expected)
    targets = ([family] if family else []) + instances
    for target in targets:
        if target is not row:
            advance(target, target.version if isinstance(target, ProjectDocument) else target.access_version)
    for target in targets or [row]:
        setattr(target, 'confidential_default' if isinstance(target, ProjectDocumentDefinition) else 'confidential', confidential)
        target.confidential_user_ids = sorted(set(user_ids)-{project.manager}) if confidential else []
        if confidential:
            if isinstance(target, ProjectDocumentDefinition):target.external_visible_default = False
            elif isinstance(target, ProjectDocument):target.external_visible = False
            if not isinstance(target, Attachment):target.external_never_visible = True
    if isinstance(row, Attachment):row.confidential_explicit = confidential
    db.flush()
    affected = ([row] if isinstance(row, Attachment) else db.query(Attachment).join(
        DocumentVersion, DocumentVersion.attachment_id == Attachment.id).filter(
        DocumentVersion.project_document_id.in_([document.id for document in instances])).all())
    for asset in affected:
        asset.confidential = bool(asset.confidential_explicit or any(document.confidential for document in _file_documents(asset)))
    log_change(db, project.id, 'attachment' if isinstance(row, Attachment) else 'project_document' if isinstance(row, ProjectDocument) else 'project_document_definition',
        row.id, 'confidential_acl', user.id, '项目负责人修改保密可见范围（资料要求全部期次、历史版本及以后生成项）', before,
        {'confidential': confidential, 'confidential_user_ids': row.confidential_user_ids,
         'version':row.version if isinstance(row,ProjectDocument) else row.access_version,'affected_instances':len(instances)})
    db.flush()


def owned_document(db, project_id, document_id):
    row = db.query(ProjectDocument).filter_by(id=document_id,project_id=project_id).populate_existing().first()
    if row is None:
        raise HTTPException(404,'资料不存在或不属于当前项目')
    return row


def owned_definition(db, project_id, definition_id):
    row = db.query(ProjectDocumentDefinition).filter_by(id=definition_id,project_id=project_id).populate_existing().first()
    if row is None:
        raise HTTPException(404,'资料要求不存在或不属于当前项目')
    return row


def instantiate(db, project, definition, *, vehicle=None, period_key=None, trigger_ref=None, triggered_at=None):
    """Idempotent seam for T23/T24: only the caller supplies real periods/triggers."""
    if not applicable(project,definition) or definition.stage_key == 'legacy':
        return None
    if definition.scope == 'vehicle' and (vehicle is None or vehicle.project_id != project.id):
        raise HTTPException(400,'车辆范围资料必须对应本项目车辆档案')
    if definition.timing_type == 'lifetime' and not db.query(ProjectEvent.id).filter(ProjectEvent.project_id==project.id,ProjectEvent.event_key=='internal_kickoff',or_(ProjectEvent.actual_at.isnot(None), ProjectEvent.actual_date.isnot(None))).first():
        raise HTTPException(400,'全周期资料等待内部启动会真实登记后建档')
    if definition.timing_type == 'weekly' and not period_key:
        raise HTTPException(400,'每周资料必须指定真实周次')
    if definition.timing_type == 'on_trigger' and (not trigger_ref or not isinstance(triggered_at,datetime)):
        raise HTTPException(400,'触发资料必须关联真实触发记录及其发生时间')
    if definition.timing_type == 'on_trigger':
        from app.models import DocumentTriggerEvent
        from app.services.document_deadlines import utc
        source=db.get(DocumentTriggerEvent,trigger_ref)
        if source is None or source.project_id!=project.id or source.trigger_type!=definition.trigger_type or utc(source.occurred_at)!=utc(triggered_at):
            raise HTTPException(400,'触发来源、项目、性质与真实时刻不匹配')
    key = ':'.join((definition.id, vehicle.id if vehicle else '-', period_key or '-', trigger_ref or '-'))
    # Migrated records keep their original source key and identity after explicit classification.
    row = db.query(ProjectDocument).filter_by(project_id=project.id,definition_id=definition.id,
        vehicle_unit_id=vehicle.id if vehicle else None,period_key=period_key,trigger_ref=trigger_ref).first()
    if row:
        return row
    row = ProjectDocument(project_id=project.id,definition_id=definition.id,requirement_id=definition.requirement_id,
        instance_key=key,vehicle_unit_id=vehicle.id if vehicle else None,vehicle_label=vehicle.asset_code if vehicle else '',
        period_key=period_key,trigger_ref=trigger_ref,triggered_at=triggered_at.astimezone(timezone.utc).replace(tzinfo=None) if triggered_at and triggered_at.tzinfo else triggered_at,confidential=definition.confidential_default,
        confidential_user_ids=deepcopy(definition.confidential_user_ids or []),
        external_visible=definition.external_visible_default and not definition.confidential_default and not definition.external_never_visible,
        external_never_visible=definition.external_never_visible, owner_id=definition.owner_id, **{key:deepcopy(getattr(definition,key)) for key in RULE_FIELDS})
    db.add(row);db.flush()
    return row


def materialize_static(db, project, actor_id=None, now=None):
    db.flush()  # SessionLocal disables autoflush; consume the just-recorded real event.
    definitions = db.query(ProjectDocumentDefinition).filter_by(project_id=project.id).all()
    units = db.query(VehicleUnit).filter_by(project_id=project.id).all()
    for definition in definitions:
        if definition.stage_key == 'legacy' or definition.timing_type in DEFERRED_TYPES or not applicable(project,definition):
            continue
        if definition.timing_type == 'lifetime' and not db.query(ProjectEvent.id).filter(ProjectEvent.project_id==project.id,ProjectEvent.event_key=='internal_kickoff',or_(ProjectEvent.actual_at.isnot(None), ProjectEvent.actual_date.isnot(None))).first():
            continue
        for vehicle in units if definition.scope == 'vehicle' else [None]:
            instantiate(db,project,definition,vehicle=vehicle)
    db.flush()
    from app.services.document_deadlines import refresh_project
    refresh_project(db, project,actor_id=actor_id,now=now)


def initialize(db, project):
    tid = None if project.template_id in (None,'default') else project.template_id
    requirements = db.query(DocumentRequirement).filter_by(template_id=tid,is_group=False).order_by(DocumentRequirement.sort_order).all()
    existing = {row.source_key for row in db.query(ProjectDocumentDefinition).filter_by(project_id=project.id)}
    for rule in requirements:
        source_key = 'template:'+rule.id
        if source_key in existing:
            continue
        db.add(ProjectDocumentDefinition(project_id=project.id,requirement_id=rule.id,source_key=source_key,
            **{key:deepcopy(getattr(rule,key)) for key in RULE_FIELDS+DEFAULT_FIELDS}))
    db.flush();materialize_static(db,project)


def waiting_reason(project, definition, count):
    if definition.stage_key == 'legacy': return '历史待分类，请负责人明确归入第4–9阶段'
    if not applicable(project,definition): return '不适用于当前调度平台'
    if count: return None
    if definition.timing_type == 'weekly': return '等待按周生成当期资料'
    if definition.timing_type == 'on_trigger': return '等待真实事件触发'
    if definition.timing_type == 'lifetime': return '等待内部启动会登记后建档'
    if definition.scope == 'vehicle': return '等待车辆档案建齐后逐车生成'
    return '等待生成资料实例'


def file_dict(asset, users=None):
    users = users or {}
    from app.services.file_retention import removal_payload
    storage=removal_payload(asset)
    return {key:getattr(asset,key) for key in ('id','filename','file_size','content_type','sha256','uploaded_by','confidential','confidential_explicit','confidential_user_ids','access_version','entity_type','entity_id','category')} | {
        'confidential':file_is_confidential(asset),
        'uploaded_by_name':users.get(asset.uploaded_by,''),'uploaded_at':iso(asset.uploaded_at),'download_url':f'/files/{asset.id}/download' if storage['storage_state']=='available' else '',**storage}


def view(db, project, user, *, vehicle_unit_id=None, audit=False):
    document_query=db.query(ProjectDocument).filter_by(project_id=project.id)
    definition_query=db.query(ProjectDocumentDefinition).filter_by(project_id=project.id)
    if vehicle_unit_id is not None:
        document_query=document_query.filter(ProjectDocument.scope=='vehicle',ProjectDocument.vehicle_unit_id==vehicle_unit_id)
        definition_query=definition_query.filter(ProjectDocumentDefinition.scope=='vehicle')
    documents=document_query.order_by(ProjectDocument.sort_order,ProjectDocument.code,ProjectDocument.vehicle_label).all()
    definitions=definition_query.order_by(ProjectDocumentDefinition.sort_order,ProjectDocumentDefinition.code).all()
    if vehicle_unit_id is not None:
        definitions=[row for row in definitions if applicable(project,row)]
    versions = db.query(DocumentVersion).filter(DocumentVersion.project_document_id.in_([d.id for d in documents])).order_by(DocumentVersion.uploaded_at.asc().nullsfirst(),DocumentVersion.id).all()
    assets = {row.id:row for row in db.query(Attachment).filter_by(project_id=project.id)}
    actor_ids={v.uploaded_by for v in versions}|{a.uploaded_by for a in assets.values()}
    for version in versions:
        metadata=version.review_metadata or {}
        for review in [metadata.get('latest_review'),*(metadata.get('review_history') or [])]:
            if isinstance(review,dict) and isinstance(review.get('by'),str):actor_ids.add(review['by'])
    users = {row.id:row.display_name for row in db.query(User).filter(User.id.in_(actor_ids))}
    version_map = defaultdict(list)
    for version in versions:
        asset = assets.get(version.attachment_id)
        if asset is None or not can_read_file(user,project,asset): continue
        row = {key:getattr(version,key) for key in ('id','attachment_id','uploaded_by','note','review_metadata')}
        metadata=deepcopy(version.review_metadata)
        if isinstance(metadata,dict):
            for review in [metadata.get('latest_review'),*(metadata.get('review_history') or [])]:
                if isinstance(review,dict):review['by_name']=users.get(review.get('by'),'原审核人已不存在或未记录')
        row['review_metadata']=metadata
        row.update(filename=asset.filename,file_size=asset.file_size,sha256=asset.sha256,uploaded_at=iso(version.uploaded_at),
            uploaded_by_name=users.get(version.uploaded_by,''),file=file_dict(asset,users),download_url=f'/projects/{project.id}/documents/{version.project_document_id}/versions/{version.id}/download')
        from app.services.file_retention import removal_payload
        row.update(removal_payload(asset))
        if row['storage_state']=='removed_by_policy':row['download_url']=''
        if not can_read_file(user,project,asset):
            row.update(filename='保密附件（未获查看权限）',file_size=0,sha256=None,note='',review_metadata=None,download_url='',restricted=True,file=None,storage_state='available',removal=None)
        version_map[version.project_document_id].append(row)
    result=[]
    from app.services import document_deadlines as deadlines
    owner_users=deadlines._users(db,project,[*documents,*definitions])
    from app.models import DocumentTriggerEvent
    from app.services.document_triggers import event_dict
    triggers={row.id:row for row in db.query(DocumentTriggerEvent).filter_by(project_id=project.id)}
    for document in documents:
        if not can_read_document(user,project,document): continue
        data={column.key:getattr(document,column.key) for column in document.__table__.columns}
        for key in ('created_at','submitted_at','due_at','triggered_at'):data[key]=iso(data[key])
        data.update(deadlines.owner_details(project,document,owner_users))
        data['due_state']=deadlines.due_state(document,project)
        data['trigger_event']=event_dict(triggers[document.trigger_ref]) if document.trigger_ref in triggers else None
        data.update(versions=version_map[document.id],latest_version=version_map[document.id][-1] if version_map[document.id] else None,applicable=applicable(project,document))
        result.append(data)
    count=defaultdict(int)
    for document in documents:count[document.definition_id]+=1
    definition_rows=[]
    for definition in definitions:
        if not can_read_definition(user,project,definition):continue
        data={column.key:getattr(definition,column.key) for column in definition.__table__.columns}
        data['created_at']=iso(definition.created_at)
        data.update(deadlines.owner_details(project,definition,owner_users))
        data.update(waiting_reason=waiting_reason(project,definition,count[definition.id]),instance_count=count[definition.id])
        definition_rows.append(data)
    can_manage=C_PLAN in project_capabilities(user,project)
    classified={version.attachment_id for version in versions}
    from app.services.storage_cleanup import storage_warnings
    unclassified=[a for a in assets.values() if vehicle_unit_id is None and a.id not in classified and can_read_file(user,project,a)]
    if audit:
        audit_access(db,project,user,documents=[d for d in documents if d.id in {r['id'] for r in result}],
            definitions=[d for d in definitions if d.id in {r['id'] for r in definition_rows}],
            files=unclassified+[assets[v['attachment_id']] for r in result for v in r['versions']])
        db.commit()
    return {'documents':result,'definitions':definition_rows,'unclassified_files':[file_dict(a,users) for a in unclassified],
        'storage_warnings':storage_warnings(db,project,user,vehicle_unit_id=vehicle_unit_id),
        'trigger_events':[event_dict(row) for row in triggers.values()],
        'document_actions':deadlines.action_summary(db,project,user,documents=documents,users=owner_users),
        'owner_options':[{'id':person.id,'name':person.display_name} for person in sorted(owner_users.values(),key=lambda person:(person.display_name,person.id)) if person.is_active and has_permission(person,'project.read',default=True) and person.id in {project.manager,project.technical_manager,*(project.members or [])}] if can_manage else [],
        'permissions':{'manage':can_manage,'submit':can_submit(user,project),'manage_confidentiality':user.id==project.manager and can_manage},'timezone':project.timezone,'version':project.version}


def save_definition(db, project, body, user, definition_id=None):
    if body.stage_key == 'legacy' or body.is_group or body.parent_id:
        raise HTTPException(400,'项目资料要求需明确归入第4–9阶段，不能伪造历史来源或分组')
    row=owned_definition(db,project.id,definition_id) if definition_id else ProjectDocumentDefinition(project_id=project.id,source_key='custom:'+str(uuid4()),created_by=user.id)
    if definition_id and not can_read_definition(user,project,row):raise HTTPException(403,'无权修改该保密资料要求')
    if definition_id and any(getattr(body,key)!=getattr(row,key) for key in DEFAULT_FIELDS):
        raise HTTPException(409,'现有资料的可见范围需通过带版本校验的保密或外部授权设置修改')
    if not definition_id and user.id!=project.manager and body.confidential_default:
        raise HTTPException(403,'仅项目负责人可设置保密资料要求')
    before={column.key:(iso(getattr(row,column.key)) if isinstance(getattr(row,column.key),datetime) else deepcopy(getattr(row,column.key))) for column in row.__table__.columns} if row.id else None
    from app.services.document_deadlines import validate_owner
    if 'owner_id' in body.model_fields_set:validate_owner(db,project,body.owner_id)
    old_stage,old_scope=row.stage_key,row.scope
    previous_identity=tuple(getattr(row,key) for key in IDENTITY_FIELDS)
    duplicate=db.query(ProjectDocumentDefinition).filter(ProjectDocumentDefinition.project_id==project.id,ProjectDocumentDefinition.code==body.code).first()
    if duplicate and duplicate.id!=row.id:raise HTTPException(409,'当前项目已有相同编号的资料要求')
    excluded={'is_group','parent_id'} | ({'owner_id'} if 'owner_id' not in body.model_fields_set else set())
    for key,value in body.model_dump(exclude=excluded).items():
        setattr(row,key,value)
    db.add(row);db.flush()
    if old_stage=='legacy' and old_scope==row.scope:
        for document in db.query(ProjectDocument).filter_by(definition_id=row.id,stage_key='legacy'):
            for key in RULE_FIELDS:
                if key not in {'source_metadata','blank_file_id'}:setattr(document,key,deepcopy(getattr(row,key)))
            if 'owner_id' in body.model_fields_set:document.owner_id=body.owner_id
    elif previous_identity==tuple(getattr(row,key) for key in IDENTITY_FIELDS):
        for document in db.query(ProjectDocument).filter_by(definition_id=row.id):
            if document.status=='submitted' or db.query(DocumentVersion.id).filter_by(project_document_id=document.id).first():
                continue
            for key in RULE_FIELDS:
                if key not in {'source_metadata','blank_file_id'}:setattr(document,key,deepcopy(getattr(row,key)))
            if 'owner_id' in body.model_fields_set:document.owner_id=body.owner_id
            document.confidential=row.confidential_default
            document.external_never_visible=row.external_never_visible
            document.external_visible=row.external_visible_default and not row.confidential_default and not row.external_never_visible
            bump_version(document,None,db=db)
    materialize_static(db,project,actor_id=user.id)
    log_change(db,project.id,'project_document_definition',row.id,'update' if before else 'create',user.id,
        f'资料要求：{row.code} {row.name}',before,{**{key:getattr(row,key) for key in RULE_FIELDS+DEFAULT_FIELDS},'owner_id':row.owner_id})
    db.flush();return row


def file_path(asset):
    from app.services.file_retention import removal_record
    record=removal_record(asset)
    if record is not None:raise HTTPException(410,f'该历史原件已于{record.removed_at.date()}按明确授权策略清理；保留原文件名、校验值、提交记录及清理凭据，原字节不再可下载')
    stored=asset.stored_name
    path=UPLOAD_DIR/stored
    if not stored or Path(stored).name!=stored or '\\' in stored or path.is_symlink() or path.resolve().parent!=UPLOAD_DIR.resolve() or not path.is_file():
        raise HTTPException(404,'附件原件缺失或路径无效，请核对原始文件')
    return path


def validate_file(asset, *, update_hash=False):
    path=file_path(asset);sha=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):sha.update(chunk)
    if path.stat().st_size!=asset.file_size or (asset.sha256 and asset.sha256!=sha.hexdigest()):
        raise HTTPException(409,'附件原件完整性校验失败，未提交资料')
    if update_hash:asset.sha256=sha.hexdigest()
    return path


def next_document_recorded_at(db, document_id, now=None):
    """Project lock serializes writes; recording order survives clock ties/regression."""
    from datetime import timedelta
    previous=db.query(DocumentVersion.uploaded_at).filter_by(project_document_id=document_id).order_by(
        DocumentVersion.uploaded_at.desc().nullslast(),DocumentVersion.id.desc()).first()
    candidate=now or utcnow()
    try:
        return max(candidate,previous[0]+timedelta(microseconds=1)) if previous and previous[0] else candidate
    except OverflowError:
        raise HTTPException(409,'原版本记录时间已超出可递增范围，请管理员核对原始记录') from None


def submit(db, project, document_ids, attachment_id, user, note=''):
    if not document_ids or len(document_ids)>100 or len(set(document_ids))!=len(document_ids):
        raise HTTPException(400,'请选择1–100个不同的资料项')
    documents=[owned_document(db,project.id,identity) for identity in document_ids]
    asset=db.query(Attachment).filter_by(id=attachment_id,project_id=project.id).populate_existing().first()
    if asset is None:raise HTTPException(400,'必须选择真实存在的本项目附件才能提交')
    if not can_read_file(user,project,asset):raise HTTPException(403,'没有该保密附件的使用权限')
    validate_file(asset,update_hash=True)
    for document in documents:
        if not can_read_document(user,project,document):raise HTTPException(403,'没有该保密资料的提交权限')
        if not applicable(project,document):raise HTTPException(400,'资料不适用于当前平台，请先核对平台或要求')
    if any(row.confidential for row in documents):asset.confidential=True
    now=utcnow()
    for document in documents:
        before={'status':document.status,'version':document.version}
        recorded_at=next_document_recorded_at(db,document.id,now)
        version=DocumentVersion(project_document_id=document.id,attachment_id=asset.id,uploaded_by=user.id,uploaded_at=recorded_at,note=note)
        db.add(version);document.status='submitted';document.waived_reason='';document.submitted_by=user.id;document.submitted_at=recorded_at
        bump_version(document,None,db=db);db.flush()
        log_change(db,project.id,'project_document',document.id,'submit',user.id,f'提交资料：{document.code} {document.name}',before,
            {'status':'submitted','version_id':version.id,'attachment_id':asset.id,'sha256':asset.sha256})
    if project.manager and project.manager!=user.id:
        from app.routers.notifications import notify
        for document in documents:
            notify(db,project.manager,f'资料已提交：{document.name}'[:200],f'{user.display_name}提交了新版本',ntype='document_submitted',project_id=project.id,entity_id=document.id)
    return documents


def create_attachment(db, project, data, filename, content_type, user, *, entity_type='project',entity_id='',category=''):
    if not data or len(data)>MAX_UPLOAD_SIZE:raise HTTPException(413 if data else 400,f'文件为空或超过当前{MAX_UPLOAD_SIZE//1024//1024}MB限制')
    if not filename or len(filename)>300 or '/' in filename or '\\' in filename or any(ord(ch)<32 for ch in filename):
        raise HTTPException(400,'文件名无效')
    content_type=content_type or 'application/octet-stream'
    if not re.fullmatch(r'[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+',content_type) or len(content_type)>100:
        raise HTTPException(400,'文件类型无效')
    if entity_type not in {'project','task','issue'}:raise HTTPException(400,'文件挂载对象无效')
    if entity_type=='project' and entity_id not in ('',project.id):raise HTTPException(400,'文件挂载项目与当前项目不一致')
    if entity_type!='project':
        model=Task if entity_type=='task' else Issue
        entity=db.get(model,entity_id)
        if entity is None or entity.project_id!=project.id:raise HTTPException(400,'文件挂载对象不属于当前项目')
    stored=uuid4().hex;path=UPLOAD_DIR/stored
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);track_new_file(db,path)
    with os.fdopen(fd,'wb') as handle:
        handle.write(data);handle.flush();os.fsync(handle.fileno())
    directory=os.open(UPLOAD_DIR,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(directory)
    finally:os.close(directory)
    asset=Attachment(project_id=project.id,filename=filename,stored_name=stored,file_size=len(data),content_type=content_type,
        uploaded_by=user.id,sha256=hashlib.sha256(data).hexdigest(),entity_type=entity_type,entity_id=entity_id,category=category[:50])
    db.add(asset);db.flush();log_change(db,project.id,'attachment',asset.id,'create',user.id,f'上传文件：{filename}',None,{'sha256':asset.sha256,'file_size':len(data)})
    return asset


def update_state(db,project,document,user,status,reason,expected=None):
    if status not in {'pending','waived'}:raise HTTPException(400,'提交资料必须使用真实附件提交入口')
    if (status=='waived' or document.status=='submitted') and not reason.strip():raise HTTPException(400,'标记不适用或撤回已提交资料必须填写理由')
    if not can_read_document(user,project,document):raise HTTPException(403,'无权操作该保密资料')
    before={'status':document.status,'waived_reason':document.waived_reason,'submitted_at':iso(document.submitted_at),'submitted_by':document.submitted_by}
    bump_version(document,expected,db=db);document.status=status;document.waived_reason=reason.strip() if status=='waived' else ''
    document.submitted_at=None;document.submitted_by=None
    from app.services.document_deadlines import refresh_project
    refresh_project(db,project,actor_id=user.id,generate=False)
    log_change(db,project.id,'project_document',document.id,'waive' if status=='waived' else 'withdraw',user.id,
        f'资料{document.name}：'+reason.strip(),before,{'status':status,'reason':reason.strip()})


def progress_summary(db,project,user,documents=None):
    documents=documents if documents is not None else db.query(ProjectDocument).filter_by(project_id=project.id)
    rows=[row for row in documents if applicable(project,row) and can_read_document(user,project,row)]
    from app.services.lifecycle_gates import _pending_required_documents
    return {'phase4_ready': not _pending_required_documents(db, project.id, stages=('4',), verify_files=False), 'total':len(rows),'pending':sum(row.status=='pending' for row in rows),
        'submitted':sum(row.status=='submitted' for row in rows),'waived':sum(row.status=='waived' for row in rows),
        'required_pending':sum(row.required and row.status=='pending' and row.stage_key!='legacy' for row in rows)}


def clone_definitions(db,source,target,user):
    for definition in db.query(ProjectDocumentDefinition).filter_by(project_id=source.id).order_by(ProjectDocumentDefinition.sort_order):
        if not can_read_definition(user,source,definition):
            continue
        fields={key:deepcopy(getattr(definition,key)) for key in RULE_FIELDS+DEFAULT_FIELDS}
        if definition.blank_file_id:
            asset=db.get(DocumentTemplateFile,definition.blank_file_id)
            if asset is None or not can_read_blank(db,user,asset,source):fields['blank_file_id']=None
        db.add(ProjectDocumentDefinition(project_id=target.id,requirement_id=definition.requirement_id,
            source_key='clone:'+definition.id,created_by=user.id,
            **fields))
    db.flush();materialize_static(db,target)


def export_snapshot(db,project,user=None):
    """Portable planning import keeps history as provenance, never forged new evidence."""
    import base64
    from app.services.document_requirements import file_dict as blank_dict
    from app.models import DocumentTriggerEvent
    if user is None:raise ValueError('便携资料导出必须提供当前账号；完整恢复使用私有加密快照')
    definitions=db.query(ProjectDocumentDefinition).filter_by(project_id=project.id).order_by(ProjectDocumentDefinition.sort_order).all()
    if user is not None:
        definitions=[row for row in definitions if can_read_definition(user,project,row)]
    definition_ids={row.id for row in definitions};blanks={};total=0
    packed=[]
    for definition in definitions:
        row={key:deepcopy(getattr(definition,key)) for key in RULE_FIELDS+DEFAULT_FIELDS}
        row.update(source_id=definition.id,source_key=definition.source_key,blank_file_key=row.pop('blank_file_id'))
        packed.append(row)
        key=definition.blank_file_id
        if key and key not in blanks:
            asset=db.get(DocumentTemplateFile,key)
            if asset is None:raise HTTPException(409,'项目空白模板元数据缺失，不能生成完整便携导出')
            if not can_read_blank(db,user,asset,project):
                row['blank_file_key']=None
                continue
            content=read_asset(asset);total+=len(content)
            if total>MAX_UPLOAD_SIZE:raise HTTPException(413,'项目空白模板总量超过10MB便携限制，请使用完整加密备份')
            blanks[key]={**blank_dict(asset),'data':base64.b64encode(content).decode()};blanks[key].pop('id')
    documents=db.query(ProjectDocument).filter_by(project_id=project.id).order_by(ProjectDocument.id).all()
    if user is not None:documents=[row for row in documents if can_read_document(user,project,row) and row.definition_id in definition_ids]
    ids={row.id for row in documents}
    def serial(row):
        return {column.key:(iso(getattr(row,column.key)) if isinstance(getattr(row,column.key),datetime) else deepcopy(getattr(row,column.key))) for column in row.__table__.columns}
    versions=[]
    for version in db.query(DocumentVersion).filter(DocumentVersion.project_document_id.in_(ids)).order_by(DocumentVersion.id):
        asset=db.get(Attachment,version.attachment_id)
        if user is not None and asset and not can_read_file(user,project,asset):continue
        versions.append({**serial(version),'file':file_dict(asset) if asset else None})
    audit_access(db,project,user,documents=documents,definitions=definitions,
        files=[db.get(Attachment,version['attachment_id']) for version in versions if db.get(Attachment,version['attachment_id']) is not None],action='confidential_export')
    db.commit()
    return {'document_definitions':packed,'document_template_files':blanks,
            'project_documents':[serial(row) for row in documents],'document_versions':versions,
            'document_trigger_events':[serial(row) for row in db.query(DocumentTriggerEvent).filter_by(project_id=project.id)
                if row.id in {document.trigger_ref for document in documents} or row.source_metadata.get('warning')],
            'document_import_note':'JSON为新项目计划导入；源提交和审核仅作为只读来源保留，真实证据请使用完整加密备份恢复。'}


def parse_snapshot(payload):
    """Validate all portable rules/files before any project/physical-file mutation."""
    from app.services.document_requirements import parse_bundle
    rows=payload.get('document_definitions')
    if rows is None:return None
    if not isinstance(rows,list) or len(rows)>2000:raise ValueError('资料定义必须是最多2000项的数组')
    records=[];source_ids=[]
    for index,row in enumerate(rows):
        if not isinstance(row,dict):raise ValueError('资料定义每项必须是对象')
        source=row['source_id'] if 'source_id' in row else f'row-{index}'
        if not isinstance(source,str) or not source.strip() or len(source)>100:raise ValueError('资料定义来源ID无效')
        if source in source_ids:raise ValueError('资料定义来源ID重复')
        source_ids.append(source)
        record={key:row[key] for key in RULE_FIELDS+DEFAULT_FIELDS if key not in {'blank_file_id'} and key in row}
        record['blank_file_key']=row.get('blank_file_key')
        record['parent_code']=None;record['is_group']=False
        records.append(record)
    for key in ('project_documents','document_versions','document_trigger_events'):
        values=payload.get(key,[])
        if not isinstance(values,list) or len(values)>10000 or any(not isinstance(item,dict) for item in values):raise ValueError(f'{key}必须是有界对象数组')
    document_ids=set()
    for row in payload.get('project_documents',[]):
        identity=row.get('id');definition_id=row.get('definition_id')
        trigger=row.get('trigger_ref')
        if trigger is not None and (not isinstance(trigger,str) or not trigger.strip() or len(trigger)>100):
            raise ValueError('资料实例历史的触发来源ID无效')
        if not isinstance(identity,str) or not identity.strip() or len(identity)>36 or identity in document_ids:
            raise ValueError('资料实例历史ID无效或重复')
        if not isinstance(definition_id,str) or definition_id not in source_ids:
            raise ValueError('资料实例历史的定义来源缺失或无效')
        document_ids.add(identity)
    version_ids=set()
    for row in payload.get('document_versions',[]):
        identity=row.get('id');document_id=row.get('project_document_id')
        if not isinstance(identity,str) or not identity.strip() or len(identity)>36 or identity in version_ids:
            raise ValueError('资料版本历史ID无效或重复')
        if not isinstance(document_id,str) or document_id not in document_ids:
            raise ValueError('资料版本历史无对应实例')
        version_ids.add(identity)
    event_ids=set()
    for row in payload.get('document_trigger_events',[]):
        identity=row.get('id');source=row.get('source_id')
        if not isinstance(identity,str) or not identity.strip() or len(identity)>36 or identity in event_ids:
            raise ValueError('触发事件历史ID无效或重复')
        if not isinstance(source,str) or not source.strip() or len(source)>36:
            raise ValueError('触发事件历史来源ID无效')
        if row.get('trigger_type') not in ('accident','quality','member_leave') or row.get('source_type') not in ('issue','member_departure'):
            raise ValueError('触发事件历史类型无效')
        event_ids.add(identity)
    parsed=parse_bundle({'document_requirements':records,'document_template_files':payload.get('document_template_files',{})})
    return parsed,source_ids,deepcopy(payload.get('project_documents',[])),deepcopy(payload.get('document_versions',[])),deepcopy(payload.get('document_trigger_events',[]))


def import_snapshot(db,project,parsed,user):
    from app.services.document_requirements import create_file
    if parsed is None:return False
    bundle,source_ids,history,versions,events=parsed;definitions,files=bundle
    assets={key:create_file(db,*data,user.id).id for key,data in files.items()}
    for (body,parent,asset,source),source_id in zip(definitions,source_ids):
        values=body.model_dump(exclude={'parent_id','is_group'})
        source_history=[row for row in history if row.get('definition_id')==source_id]
        document_ids={row.get('id') for row in source_history if isinstance(row.get('id'),str)}
        values['source_metadata']={'kind':'portable_unverified_snapshot','portable_source_id':source_id,'definition':source,
            'project_documents':source_history,'document_versions':[row for row in versions if row.get('project_document_id') in document_ids],
            'document_trigger_events':[row for row in events if row.get('id') in {item.get('trigger_ref') for item in source_history}]}
        values['blank_file_id']=assets.get(asset)
        row=ProjectDocumentDefinition(project_id=project.id,source_key='import:'+str(uuid4()),created_by=user.id,**values)
        db.add(row)
    db.flush();materialize_static(db,project)
    return True


def import_legacy_requirements(db,project,payload,user):
    """Old JSON contains planning requirements, not transferable attachment ownership."""
    from uuid import uuid5,NAMESPACE_URL
    entries=[]
    for mi,module in enumerate(payload.get('modules',[])):
        for ti,task in enumerate(module.get('tasks',[])):
            for index,original in enumerate(task.get('deliverables') or []):
                item=original if isinstance(original,dict) else {'name':str(original)}
                entries.append(('task',f'{mi}:{ti}:{index}',item.get('name') or '旧交付要求',item.get('required',True),
                    {'module':deepcopy(module),'task_name':task.get('name'),'index':index,'original':deepcopy(original)}))
    for index,item in enumerate(payload.get('archive_checklist',[])):
        entries.append(('archive',str(index),item.get('item_name') or '旧归档要求',item.get('is_required',True),deepcopy(item)))
    for index,item in enumerate(payload.get('preparations',[])):
        if item.get('category')=='procurement':continue
        entries.append(('preparation',str(index),item.get('name') or '旧准备要求',item.get('is_required',True),deepcopy(item)))
    for kind,source,name,required,original in entries:
        db.add(ProjectDocumentDefinition(project_id=project.id,source_key=f'legacy-import:{kind}:{source}',stage_key='legacy',
            code='legacy.'+uuid5(NAMESPACE_URL,f'{project.id}:{kind}:{source}').hex,name=name[:300],required=bool(required),scope='project',
            timing_type='on_demand',source_metadata={'kind':'portable_legacy_unverified','source_type':kind,'original':original},created_by=user.id,
            note='旧导入要求待明确分类，源提交/审核/附件引用只保留为只读来源，不假定已满足'))
    db.flush();return bool(entries)
