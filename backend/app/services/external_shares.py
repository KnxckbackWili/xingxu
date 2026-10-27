"""A narrow external projection: every read rechecks the original current grant.

Share secrets enter only bootstrap JSON. Short audience-bound sessions carry the
share ID, never a business subject; neither token is persisted by the browser.
"""
from datetime import timedelta, timezone
import hashlib
import re
import secrets
from types import SimpleNamespace

import jwt
from fastapi import HTTPException
from sqlalchemy import update
from app import config
from app.models import (ExternalShare, ExternalAccessLog, Project, User, ProjectDocument,
                        ProjectDocumentDefinition, DocumentVersion, Attachment)
from app.services import project_documents as docs
from app.services.permissions import C_UPDATE, authorize_project
from app.services.scope import ensure_project_visible
from app.services.record_lock import lock_record
from app.services.change_log import log_change
from app.time_utils import utcnow

SCOPES = ('project_progress','vehicle_progress','signoffs','delivery_documents','selected_documents')
DEFAULT_SCOPES = ('project_progress','vehicle_progress')
SIGNOFF_CODES = frozenset(('6.10.1','6.10.2','6.10.3','6.10.4'))
EXTERNAL = SimpleNamespace(id='external-share',role='external',is_active=True)
UNAVAILABLE = '分享链接已失效或无权访问，请联系项目负责人'


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def manage(db, project_id, user, *, lock=False):
    """Security grants can be revoked on archived projects too."""
    authorized_version=user.token_version or 0
    project=ensure_project_visible(db,project_id,user)
    if lock:lock_record(db,project,conflict_detail='项目授权正在变更，请刷新后重试')
    db.refresh(user)
    if not user.is_active or (user.token_version or 0)!=authorized_version:
        raise HTTPException(401,'账号或会话已变化，请重新登录')
    project=ensure_project_visible(db,project_id,user)
    authorize_project(user,project,C_UPDATE)
    if user.role in ('external','readonly') or user.id!=project.manager:
        raise HTTPException(403,'仅当前项目负责人可管理外部查看')
    return project


def summary(row):
    return {'id':row.id,'project_id':row.project_id,'scopes':row.scopes,'document_ids':row.document_ids,
            'expires_at':iso(row.expires_at),'revoked_at':iso(row.revoked_at),'created_at':iso(row.created_at),
            'version':row.version,'expired':row.expires_at<=utcnow()}


def create(db,project,user,scopes,document_ids,expires_at):
    if not scopes or len(set(scopes))!=len(scopes) or any(scope not in SCOPES for scope in scopes):
        raise HTTPException(400,'请选择明确且不重复的分享范围')
    if document_ids and 'selected_documents' not in scopes or 'selected_documents' in scopes and not document_ids:
        raise HTTPException(400,'指定资料范围与所选资料必须同时填写')
    if len(set(document_ids))!=len(document_ids):raise HTTPException(400,'指定资料不能重复')
    now=utcnow();expires_at=expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if not now<expires_at<=now+timedelta(days=365):raise HTTPException(400,'有效期须在未来一年内')
    for identity in document_ids:
        row=db.query(ProjectDocument).filter_by(project_id=project.id,id=identity).first()
        if row is None or not selectable_document(db,project,row):
            raise HTTPException(400,'指定资料不存在或不允许对外查看')
    token=secrets.token_urlsafe(32)
    row=ExternalShare(project_id=project.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),
        scopes=list(scopes),document_ids=list(document_ids),expires_at=expires_at,created_by=user.id)
    db.add(row);db.flush()
    log_change(db,project.id,'external_share',row.id,'share_create',user.id,'创建外部只读分享',None,
        {'scopes':row.scopes,'document_ids':row.document_ids,'expires_at':iso(row.expires_at)})
    db.commit()
    return {**summary(row),'token':token}


def revoke(db,project,user,identity,version):
    row=db.query(ExternalShare).filter_by(project_id=project.id,id=identity).populate_existing().first()
    if row is None:raise HTTPException(404,'分享不存在')
    changed=db.execute(update(ExternalShare).where(ExternalShare.id==row.id,ExternalShare.version==version,
        ExternalShare.revoked_at.is_(None)).values(revoked_at=utcnow(),version=ExternalShare.version+1)
        .execution_options(synchronize_session=False))
    if changed.rowcount!=1:raise HTTPException(409,'分享已变化或已撤销，请刷新后核对')
    log_change(db,project.id,'external_share',row.id,'share_revoke',user.id,'撤销外部只读分享')
    db.commit();db.refresh(row);return summary(row)


def audit(db,request,action,status,share=None,resource_id=None):
    # Direct peer only: untrusted X-Forwarded-For never invents the audit IP.
    db.add(ExternalAccessLog(project_id=share.project_id if share else None,share_id=share.id if share else None,
        ip=(request.client.host if request.client else 'unknown')[:64],action=action,
        resource_id=resource_id if resource_id and len(resource_id)<=36 else None,status_code=status))
    db.commit()  # Serving without the required durable access evidence is a failure.


def check_share(db,row):
    if row is None or row.revoked_at or row.expires_at<=utcnow():raise HTTPException(401,UNAVAILABLE)
    project=db.query(Project).filter_by(id=row.project_id).populate_existing().first()
    if project is not None:
        lock_record(db,project,conflict_detail='项目授权正在变更，请稍后重试')
        db.refresh(row)
        if row.revoked_at or row.expires_at<=utcnow():raise HTTPException(401,UNAVAILABLE)
    creator=db.get(User,row.created_by) if row.created_by else None
    if creator is not None:db.refresh(creator)
    # Project transfer, owner disabling/removal, or loss of owner authority does
    # not leave an old owner's declassification grant alive.
    if project is None or project.deleted_at or creator is None or not creator.is_active or creator.role in ('external','readonly') or creator.id!=project.manager:
        raise HTTPException(401,UNAVAILABLE)
    from app.services.permissions import project_capabilities
    from app.services.system_permissions import has_permission
    if C_UPDATE not in project_capabilities(creator,project) or not has_permission(creator,'project.read',default=True):
        raise HTTPException(401,UNAVAILABLE)
    return project


def session_for(row):
    now=utcnow();expires=min(now+timedelta(minutes=15),row.expires_at)
    return jwt.encode({'type':'external_view','aud':'external_view','sid':row.id,'sv':row.version,
        'iat':now,'exp':expires},config.AUTH_SIGNING_KEY,algorithm=config.ALGORITHM),iso(expires)


def resolve_session(db,token):
    try:
        claims=jwt.decode(token,config.AUTH_SIGNING_KEY,algorithms=[config.ALGORITHM],audience='external_view',
            options={'require':['exp','iat','aud','sid','sv','type']})
        if claims['type']!='external_view' or not isinstance(claims['sid'],str) or len(claims['sid'])>36:raise ValueError
        row=db.query(ExternalShare).filter_by(id=claims['sid']).populate_existing().first()
        project=check_share(db,row)
        if claims['sv']!=row.version:raise ValueError
        return row,project
    except (jwt.PyJWTError,ValueError,TypeError):raise HTTPException(401,UNAVAILABLE) from None


def audit_share(db, token, *, session=False):
    """Attribute denied visits only after verifying a secret/signature; no grants."""
    if not isinstance(token,str):return None
    if not session:
        return db.query(ExternalShare).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).first() if re.fullmatch(r'[A-Za-z0-9_-]{43}',token) else None
    try:
        claims=jwt.decode(token,config.AUTH_SIGNING_KEY,algorithms=[config.ALGORITHM],audience='external_view',options={'verify_exp':False})
        if claims.get('type')!='external_view' or not isinstance(claims.get('sid'),str):return None
        return db.get(ExternalShare,claims['sid'])
    except (jwt.PyJWTError,ValueError,TypeError):return None


def bootstrap(db,token):
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise HTTPException(401,UNAVAILABLE)
    row=db.query(ExternalShare).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    project=check_share(db,row)
    session,expires=session_for(row)
    return row,project,session,expires


def selectable_document(db,project,row):
    if not docs.applicable(project,row) or not docs.can_read_document(EXTERNAL,project,row):return False
    definition=db.get(ProjectDocumentDefinition,row.definition_id) if row.definition_id else None
    return definition is None or docs.can_read_definition(EXTERNAL,project,definition)


def in_scope(share,row):
    return ('selected_documents' in share.scopes and row.id in share.document_ids or
            'signoffs' in share.scopes and row.code in SIGNOFF_CODES or
            'delivery_documents' in share.scopes and row.stage_key in ('7','8'))


def latest_file(db,project,row):
    version=db.query(DocumentVersion).filter_by(project_document_id=row.id).order_by(
        DocumentVersion.uploaded_at.desc().nullslast(),DocumentVersion.id.desc()).first()
    asset=db.get(Attachment,version.attachment_id) if version else None
    if asset is None or not docs.can_read_file(EXTERNAL,project,asset):return None
    return version,asset


def projection(db,share,project):
    result={'share_id':share.id,'project_name':project.name,'scopes':share.scopes,'expires_at':iso(share.expires_at)}
    if 'project_progress' in share.scopes:
        from app.services.progress import project_progress_tree
        progress=project_progress_tree(db,project.id)
        result['project_progress']={'status':project.status,'start_date':str(project.start_date),'end_date':str(project.end_date),
            'target':progress['target'],'completed':progress['completed'],
            'percent':progress['percent'] if progress['progress_known'] else None,'quantity_unknown':not progress['progress_known']}
    if 'vehicle_progress' in share.scopes:
        from app.services.vehicle_progress import matrix
        raw=matrix(db,project.id)
        result['vehicle_progress']={'steps':[{'key':row['key'],'name':row['name']} for row in raw['steps']],
            'units':[{**{key:row[key] for key in ('asset_code','fleet_no','vehicle_type','model_name')},
                'cells':{key:{'is_done':cell['is_done'],'done_on':cell['done_on']} for key,cell in row['cells'].items()}}
                for row in raw['units']], 'summary':raw['summary'],'warnings':raw['migration_warnings']}
    if any(key in share.scopes for key in ('signoffs','delivery_documents','selected_documents')):
        rows=db.query(ProjectDocument).filter_by(project_id=project.id).order_by(ProjectDocument.sort_order,ProjectDocument.code).all()
        result['documents']=[]
        for row in rows:
            if not in_scope(share,row) or not selectable_document(db,project,row):continue
            evidence=latest_file(db,project,row)
            # An independently restricted original hides its title/metadata too.
            if row.status=='submitted' and evidence is None:continue
            version,asset=evidence if evidence else (None,None)
            result['documents'].append({'id':row.id,'code':row.code,'name':row.name,'vehicle_label':row.vehicle_label,
                'period_key':row.period_key,'status':row.status,'file':{'version_id':version.id,'filename':asset.filename,
                    'size':asset.file_size,'uploaded_at':iso(version.uploaded_at)} if evidence else None})
    return result


def download(db,share,project,document_id,version_id):
    row=db.query(ProjectDocument).filter_by(id=document_id,project_id=project.id).first()
    if row is None or not in_scope(share,row) or not selectable_document(db,project,row):raise HTTPException(404,'资料不存在或未对本链接开放')
    evidence=latest_file(db,project,row)
    if row.status!='submitted' or not evidence or evidence[0].id!=version_id:raise HTTPException(404,'资料不存在或未对本链接开放')
    return evidence[1],docs.validate_file(evidence[1])
