"""Private, account-bound evidence uploads with bounded memory and atomic finish."""
from datetime import date,timedelta
from pathlib import Path
from uuid import uuid4,UUID
import errno,hashlib,math,os,re,shutil,logging,json

from fastapi import HTTPException
from pydantic import BaseModel,Field,field_validator
from app import config
from app.models import UploadSession,UploadChunk,Attachment,User,Task,Issue
from app.services import project_documents as docs
from app.services.change_log import log_change
from app.services.document_requirements import track_new_file
from app.time_utils import utcnow


class UploadCreate(BaseModel):
    model_config={'extra':'forbid'}
    client_uuid:str=Field(min_length=8,max_length=64)
    filename:str=Field(min_length=1,max_length=300)
    size:int=Field(gt=0,strict=True)
    sha256:str=Field(pattern='^[0-9a-f]{64}$')
    content_type:str=Field(default='application/octet-stream',max_length=100)
    document_ids:list[str]=Field(default_factory=list,max_length=100)
    note:str=Field(default='',max_length=5000)
    entity_type:str=Field(default='project',pattern='^(project|task|issue)$')
    entity_id:str=Field(default='',max_length=36)
    category:str=Field(default='',max_length=50)
    confidential:bool=False
    confidential_user_ids:list[str]=Field(default_factory=list,max_length=200)
    milestone_dates:dict[str,date]=Field(default_factory=dict,max_length=7)

    @field_validator('milestone_dates',mode='before')
    @classmethod
    def milestone_dates_valid(cls,value):
        allowed={'internal_kickoff','delivery_signed','commissioning_done','go_live','training_done','acceptance','handover'}
        if not isinstance(value,dict):raise ValueError('签单日期必须是YYYY-MM-DD映射')
        for key,raw in value.items():
            if key not in allowed or not isinstance(raw,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw):raise ValueError('签单日期必须是有效事件与YYYY-MM-DD日期映射')
            try:date.fromisoformat(raw)
            except ValueError:raise ValueError('签单日期无效') from None
        return value

    @field_validator('filename')
    @classmethod
    def filename_valid(cls,value):
        if '/' in value or '\\' in value or any(ord(ch)<32 for ch in value) or value in ('.','..'):
            raise ValueError('文件名无效')
        return value

    @field_validator('content_type')
    @classmethod
    def mime_valid(cls,value):
        value=value or 'application/octet-stream'
        if not re.fullmatch(r'[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+',value):raise ValueError('文件类型无效')
        return value

    @field_validator('document_ids','confidential_user_ids')
    @classmethod
    def ids_valid(cls,value):
        if len(value)!=len(set(value)) or any(not identity.strip() or len(identity)>36 for identity in value):
            raise ValueError('请选择不同且有效的ID')
        return sorted(value)


def private_root():
    root=config.DATA_DIR/'.upload-sessions'
    if root.is_symlink():raise HTTPException(409,'上传临时目录不可用')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.resolve().parent!=config.DATA_DIR.resolve():raise HTTPException(409,'上传临时目录不可用')
    os.chmod(root,0o700)
    return root


def session_directory(identity):
    try:
        if str(UUID(identity))!=identity:raise ValueError
    except (ValueError,TypeError,AttributeError):raise HTTPException(404,'上传会话不存在') from None
    path=private_root()/identity
    if path.is_symlink():raise HTTPException(409,'上传临时文件不可用')
    path.mkdir(mode=0o700,exist_ok=True)
    os.chmod(path,0o700)
    return path


def part_path(session,index):
    directory=session_directory(session.id);context=directory/'.context.json'
    if not context.exists():
        try:
            descriptor=os.open(context,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'w') as handle:json.dump({'project_id':session.project_id,'session_id':session.id},handle)
        except FileExistsError:pass
    path=directory/f'part-{index:08d}'
    if path.is_symlink():raise HTTPException(409,'上传分片不可用')
    return path


def digest_file(path):
    digest=hashlib.sha256();size=0
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):
            digest.update(block);size+=len(block)
    return digest.hexdigest(),size


def owned(db,pid,identity,user):
    row=db.query(UploadSession).filter_by(id=identity,project_id=pid,owner_id=user.id).populate_existing().first()
    if row is None:raise HTTPException(404,'上传会话不存在或不属于当前账号')
    return row


def validate_context(db,project,user,body,*,policy=True,completed=False):
    if not completed and body.size>config.MAX_UPLOAD_BYTES:raise HTTPException(413,'文件超过当前上传上限')
    if completed:pass
    elif body.entity_type=='project':
        if body.entity_id not in ('',project.id):raise HTTPException(400,'文件挂载项目不一致')
    else:
        entity=db.get(Task if body.entity_type=='task' else Issue,body.entity_id)
        if entity is None or entity.project_id!=project.id:raise HTTPException(400,'文件挂载对象不属于本项目')
    for identity in body.document_ids:
        document=docs.owned_document(db,project.id,identity)
        if not docs.can_read_document(user,project,document):raise HTTPException(403,'当前无权提交所选保密资料')
        if not completed and not docs.applicable(project,document):raise HTTPException(400,'所选资料不适用于当前项目平台')
    if not policy:return
    validator=getattr(docs,'validate_upload_policy',None)
    if validator is not None:
        ids=validator(db,project,user,confidential=body.confidential,user_ids=body.confidential_user_ids)
        if isinstance(body,UploadCreate):body.confidential_user_ids=sorted(ids)
    elif body.confidential or body.confidential_user_ids:
        raise HTTPException(409,'独立保密上传需先安装统一保密策略')


def intent(body):
    result={key:getattr(body,key) for key in ('filename','size','sha256','content_type','document_ids','note','entity_type','entity_id','category','confidential','confidential_user_ids','milestone_dates')}
    result['milestone_dates']={key:value.isoformat() if isinstance(value,date) else value for key,value in result['milestone_dates'].items()}
    return result


def start(db,project,user,body):
    # One owner can start uploads in different projects concurrently. Serialize
    # the owner-wide UUID/idempotency and open-session limit after project lock.
    token_version=user.token_version
    db.query(User.id).filter_by(id=user.id).with_for_update().all();db.refresh(user)
    if not user.is_active or user.token_version!=token_version:raise HTTPException(401,'账号会话已变化，请重新登录')
    if not docs.can_submit(user,project):raise HTTPException(403,'当前账号已无项目资料提交权限')
    existing=db.query(UploadSession).filter_by(owner_id=user.id,client_uuid=body.client_uuid).first()
    completed=bool(existing and existing.state=='finished')
    validate_context(db,project,user,body,policy=not completed,completed=completed)
    if completed and body.confidential:
        # At creation only this owner could designate an independent private
        # scope; the unified policy omits that implicit manager. Normalize an
        # exact retry the same way without reapplying an obsolete scope.
        body.confidential_user_ids=sorted(set(body.confidential_user_ids)-{existing.owner_id})
    if existing:
        if existing.project_id!=project.id or intent(existing)!=intent(body):raise HTTPException(409,'此上传UUID已绑定另一份文件或提交意图，请保留原请求核对')
        if existing.state!='expired' and not (existing.state=='open' and existing.expires_at<utcnow()):return existing
    count=db.query(UploadSession).filter_by(owner_id=user.id,state='open').filter(UploadSession.expires_at>utcnow()).count()
    if count>=4:raise HTTPException(409,'当前账号已有4个未完成上传，请先完成或取消后再上传')
    if existing:
        discard_parts(existing)
        db.query(UploadChunk).filter_by(session_id=existing.id).delete(synchronize_session=False)
        existing.state='open';existing.updated_at=utcnow();existing.expires_at=utcnow()+timedelta(days=config.UPLOAD_SESSION_TTL_DAYS)
        log_change(db,project.id,'upload_session',existing.id,'restart',user.id,'原意图上传过期后重新续传',None,{'client_uuid':existing.client_uuid})
        return existing
    row=UploadSession(project_id=project.id,owner_id=user.id,client_uuid=body.client_uuid,chunk_size=config.UPLOAD_CHUNK_SIZE,
        expires_at=utcnow()+timedelta(days=config.UPLOAD_SESSION_TTL_DAYS),**intent(body))
    db.add(row);db.flush()
    log_change(db,project.id,'upload_session',row.id,'create',user.id,'开始可恢复文件上传',None,
        {'client_uuid':row.client_uuid,'filename':row.filename,'size':row.size,'sha256':row.sha256,'document_ids':row.document_ids})
    return row


def open_session(row):
    if row.state!='open':raise HTTPException(409,'上传会话已经完成或取消')
    if row.expires_at<utcnow():raise HTTPException(410,'上传会话已过期，请保留本地原文件并重新开始')


def expected_size(row,index):
    total=math.ceil(row.size/row.chunk_size)
    if index<0 or index>=total:raise HTTPException(400,'上传分片编号超出范围')
    return min(row.chunk_size,row.size-index*row.chunk_size)


def payload(db,project,user,row):
    chunks=db.query(UploadChunk).filter_by(session_id=row.id).order_by(UploadChunk.chunk_index).all()
    received=[]
    if row.state=='open':
        for chunk in chunks:
            path=part_path(row,chunk.chunk_index)
            if path.is_file() and path.stat().st_size==chunk.size:
                received.append({'index':chunk.chunk_index,'size':chunk.size,'sha256':chunk.sha256})
    result={'id':row.id,'project_id':project.id,'client_uuid':row.client_uuid,'filename':row.filename,'size':row.size,
        'sha256':row.sha256,'state':'expired' if row.state=='open' and row.expires_at<utcnow() else row.state,
        'chunk_size':row.chunk_size,'total_chunks':math.ceil(row.size/row.chunk_size),'received':received,'expires_at':docs.iso(row.expires_at)}
    if row.state=='finished':result['result']=finished_result(db,project,user,row)
    return result


def finished_result(db,project,user,row):
    asset=db.query(Attachment).filter_by(id=row.attachment_id,project_id=project.id).populate_existing().first() if row.attachment_id else None
    if asset is None:raise HTTPException(410,'上传已完成，但该文件后来已被移除，请在项目资料中核对')
    if not docs.can_read_file(user,project,asset):raise HTTPException(403,'当前已无此文件的查看权限')
    documents=docs.view(db,project,user)['documents'] if row.document_ids else []
    return {'file':docs.file_dict(asset,{user.id:user.display_name}),'documents':[item for item in documents if item['id'] in row.document_ids]}


def store_part(db,project,user,row,index,incoming,sha,size):
    open_session(row);validate_context(db,project,user,row)
    if size!=expected_size(row,index):raise HTTPException(400,'分片长度与声明的文件范围不一致')
    previous=db.query(UploadChunk).filter_by(session_id=row.id,chunk_index=index).first()
    new_receipt=previous is None
    if previous and (previous.sha256!=sha or previous.size!=size):raise HTTPException(409,'同一分片编号已有不同内容，不能覆盖原上传')
    destination=part_path(row,index)
    valid=destination.is_file() and digest_file(destination)==(sha,size)
    if not valid:
        os.replace(incoming,destination)
    if new_receipt:
        previous=UploadChunk(project_id=project.id,session_id=row.id,chunk_index=index,size=size,sha256=sha)
        db.add(previous)
    if new_receipt or not valid:
        log_change(db,project.id,'upload_session',row.id,'chunk',user.id,'保存经校验的上传分片',None,{'index':index,'size':size,'sha256':sha})
    row.updated_at=utcnow();row.expires_at=row.updated_at+timedelta(days=config.UPLOAD_SESSION_TTL_DAYS)
    db.flush()
    return {'index':index,'size':size,'sha256':sha}


def finish(db,project,user,row):
    validate_context(db,project,user,row,policy=row.state!='finished',completed=row.state=='finished')
    if row.state=='finished':return row
    open_session(row)
    authenticated_version=user.token_version
    chunks=db.query(UploadChunk).filter_by(session_id=row.id).order_by(UploadChunk.chunk_index).all()
    if [item.chunk_index for item in chunks]!=list(range(math.ceil(row.size/row.chunk_size))):raise HTTPException(409,'文件分片尚未齐全，请继续原会话')
    assembled=session_directory(row.id)/('assembling-'+uuid4().hex)
    try:
        fd=os.open(assembled,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        digest=hashlib.sha256();size=0
        with os.fdopen(fd,'wb') as target:
            for chunk in chunks:
                path=part_path(row,chunk.chunk_index)
                if not path.is_file():raise HTTPException(409,f'分片{chunk.chunk_index}缺失，请重新发送该分片')
                part_hash=hashlib.sha256();part_size=0
                with path.open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        target.write(block);digest.update(block);part_hash.update(block);size+=len(block);part_size+=len(block)
                if (part_hash.hexdigest(),part_size)!=(chunk.sha256,expected_size(row,chunk.chunk_index)):
                    raise HTTPException(409,f'分片{chunk.chunk_index}完整性校验失败，请重新发送该分片')
            target.flush();os.fsync(target.fileno())
        if size!=row.size or digest.hexdigest()!=row.sha256:raise HTTPException(409,'完整文件SHA-256或长度不匹配，未建立附件及资料版本')
        # Merging can take time: re-read the actor immediately before publishing.
        db.query(User.id).filter_by(id=user.id).with_for_update().all();db.refresh(user)
        if user.token_version!=authenticated_version:raise HTTPException(401,'账号会话在文件合并期间已变化，请重新登录')
        from app.services.scope import ensure_project_visible
        ensure_project_visible(db,project.id,user)
        if not user.is_active or not docs.can_submit(user,project):raise HTTPException(403,'当前账号已无项目资料提交权限')
        validate_context(db,project,user,row)
        stored=uuid4().hex;destination=config.UPLOAD_DIR/stored
        os.link(assembled,destination);track_new_file(db,destination)
        descriptor=os.open(config.UPLOAD_DIR,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
        asset=Attachment(project_id=project.id,filename=row.filename,stored_name=stored,file_size=size,sha256=row.sha256,
            content_type=row.content_type,uploaded_by=user.id,entity_type=row.entity_type,entity_id=row.entity_id,category=row.category)
        db.add(asset);db.flush()
        policy=getattr(docs,'apply_upload_confidentiality',None)
        if policy:policy(db,project,user,asset,confidential=row.confidential,user_ids=row.confidential_user_ids)
        pending={identity for identity in row.document_ids if docs.owned_document(db,project.id,identity).status=='pending'}
        if row.document_ids:docs.submit(db,project,row.document_ids,asset.id,user,row.note)
        from app.services.project_events import record_document_dates
        record_document_dates(db,project,row.document_ids,asset.id,{key:date.fromisoformat(value) for key,value in row.milestone_dates.items()},user.id,pending_ids=pending)
        row.state='finished';row.attachment_id=asset.id;row.updated_at=utcnow()
        log_change(db,project.id,'attachment',asset.id,'create',user.id,'完成并校验可恢复上传',None,
            {'session_id':row.id,'client_uuid':row.client_uuid,'file_size':size,'sha256':row.sha256})
        db.flush();return row
    except OSError as error:
        if error.errno in (errno.ENOSPC,errno.EDQUOT):raise HTTPException(507,'存储空间不足，请保留本地原文件稍后续传') from None
        raise
    finally:assembled.unlink(missing_ok=True)


def discard_parts(row):
    try:
        directory=private_root()/row.id
        if directory.is_dir() and not directory.is_symlink():shutil.rmtree(directory)
    except OSError:logging.getLogger(__name__).warning('Private upload cache cleanup deferred for %s',row.id)
