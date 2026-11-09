"""Direct owner transfer; security identity and membership change in one transaction."""
from fastapi import HTTPException
from sqlalchemy import select
from app.models import User,ProjectDocumentDefinition
from app.services.scope import ensure_project_visible
from app.services.permissions import authorize_project,C_UPDATE
from app.services.system_permissions import has_permission
from app.services.record_lock import lock_record
from app.services.optimistic import bump_version
from app.services.change_log import log_change
from app.services.document_triggers import transfer_departures,removal_preview,confirm_removals,member_events
from app.services import project_documents as docs


def _authority(project,user):
    authorize_project(user,project,C_UPDATE)
    from app.services.project_lifecycle import ensure_project_writable
    ensure_project_writable(project)


def authorize(db,project_id,user,*,lock=False,target_id=None):
    version=user.token_version or 0
    project=ensure_project_visible(db,project_id,user)
    _authority(project,user)
    if lock:
        lock_record(db,project,conflict_detail='项目负责人正在变化，请刷新后重试')
        # Account/policy editors use this same first User anchor. Locking an
        # arbitrary recipient before it would invert their order on PostgreSQL.
        anchor=db.query(User).filter_by(username='admin').first() or db.query(User).order_by(User.id).first()
        if anchor:lock_record(db,anchor,conflict_detail='账号授权正在变化，请刷新后重试')
        ids=sorted({identity for identity in (user.id,project.manager,target_id) if identity and (anchor is None or identity!=anchor.id)})
        db.execute(select(User.id).where(User.id.in_(ids)).order_by(User.id).with_for_update()).all()
    db.refresh(user)
    if not user.is_active or (user.token_version or 0)!=version:raise HTTPException(401,'账号或会话已变化，请重新登录')
    project=ensure_project_visible(db,project_id,user)
    _authority(project,user)
    if project.manager:db.get(User,project.manager,populate_existing=True)
    return project


def eligible(person):
    return bool(person and person.is_active and has_permission(person,'project.update'))


def preview(db,project,user):
    removed=transfer_departures(db,project)
    result=removal_preview(db,project,removed)
    rules={row.code:row for row in db.query(ProjectDocumentDefinition).filter_by(project_id=project.id)}
    for person in result['removed']:
        for rule in person['documents']:
            definition=rules.get(rule['code'])
            if definition is None or not docs.can_read_definition(user,project,definition):
                rule.update(name='保密资料留存要求',restricted=True)
    current=db.get(User,project.manager) if project.manager else None
    result['current_manager']={'id':project.manager,'name':current.display_name if current else '未指定'}
    result['candidates']=[{'id':person.id,'name':person.display_name} for person in db.query(User).filter(User.is_active.is_(True)).order_by(User.display_name,User.id)
                          if person.id!=project.manager and eligible(person)]
    return result


def transfer(db,project_id,user,body):
    project=authorize(db,project_id,user,lock=True,target_id=body.target_manager_id)
    if (project.version or 0)!=body.version:raise HTTPException(409,'项目已变化，请刷新负责人和离场资料预览后重试')
    target=db.get(User,body.target_manager_id,populate_existing=True)
    if not eligible(target):raise HTTPException(400,'请选择仍启用的账号')
    if target.id==project.manager:raise HTTPException(400,'接收人已经是当前负责人')
    removed=transfer_departures(db,project)
    try:confirm_removals(db,project,removed,body.member_removal_confirmations)
    except HTTPException as exc:
        if isinstance(exc.detail,dict) and exc.detail.get('code')=='member_removal_confirmation_required':
            raise HTTPException(409,{**exc.detail,**preview(db,project,user)}) from None
        raise
    old={'manager':project.manager}
    bump_version(project,body.version,db=db)
    previous=project.manager
    project.manager=target.id
    member_events(db,project,removed,user.id)
    log_change(db,project.id,'project',project.id,'transfer',user.id,'直接更换项目负责人：'+body.reason.strip(),
        old,{'manager':target.id,'reason':body.reason.strip(),'removed_user_ids':sorted(removed)})
    from app.services.notify import notify
    notify(db,target.id,'你已成为项目「'+project.name+'」的负责人','请核对项目资料并接手后续工作',ntype='project_membership',project_id=project.id)
    old_person=db.get(User,previous) if previous else None
    if old_person and old_person.is_active and old_person.id!=user.id:
        notify(db,old_person.id,'项目「'+project.name+'」的负责人已更换','新负责人：'+target.display_name,ntype='project_membership',project_id=project.id)
    db.commit()
    from app.services.cache import cache_clear
    cache_clear('dashboard:')
    return project
