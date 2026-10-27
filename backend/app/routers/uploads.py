"""Raw bounded chunks; private staging is never mounted or directly downloadable."""
from pathlib import Path
from uuid import uuid4
import errno,hashlib,os
from fastapi import APIRouter,Depends,HTTPException,Request,Header,Response
from sqlalchemy.orm import Session
from app import config
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services import project_documents as docs,resumable_uploads as uploads
from app.services.scope import ensure_project_visible
from app.services.record_lock import lock_record
from app.services.system_permissions import route_permission,has_permission
from app.services.change_log import log_change
from app.time_utils import utcnow

def private_response(response:Response):response.headers['Cache-Control']='private, no-store'

router=APIRouter(tags=['可恢复上传'],dependencies=[Depends(private_response)])


def current(db,pid,identity,user,*,write=True,context=True):
    token_version=user.token_version
    row=uploads.owned(db,pid,identity,user)
    if write and row.state!='finished':project=docs.writable(db,pid,user,'worker.deliver')
    else:
        project=ensure_project_visible(db,pid,user)
        lock_record(db,project,conflict_detail='上传状态与项目修改冲突，请稍后重试')
        db.refresh(user);project=ensure_project_visible(db,pid,user)
        if not user.is_active:raise HTTPException(401,'账号已停用，请重新登录')
        if not docs.can_submit(user,project):raise HTTPException(403,'当前账号已无资料提交权限')
    if user.token_version!=token_version:raise HTTPException(401,'账号会话已变化，请重新登录')
    row=uploads.owned(db,pid,identity,user)
    if context:uploads.validate_context(db,project,user,row,policy=row.state!='finished',completed=row.state=='finished')
    return project,row


@router.get('/storage/limits')
@route_permission('project.read')
def limits(user:User=Depends(get_current_user)):
    if not has_permission(user,'project.read',default=True):raise HTTPException(403,'没有项目读取权限')
    return {'max_upload_size':config.MAX_UPLOAD_BYTES,'chunk_size':config.UPLOAD_CHUNK_SIZE,
        'session_ttl_days':config.UPLOAD_SESSION_TTL_DAYS,'buffered_upload_limit':config.MAX_UPLOAD_SIZE}


@router.post('/projects/{project_id}/uploads')
@route_permission('worker.deliver')
def start_upload(project_id:str,body:uploads.UploadCreate,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,'worker.deliver')
    row=uploads.start(db,project,user,body)
    db.commit();return uploads.payload(db,project,user,row)


@router.get('/projects/{project_id}/uploads/{session_id}')
@route_permission('worker.deliver')
def upload_status(project_id:str,session_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project,row=current(db,project_id,session_id,user,write=False)
    return uploads.payload(db,project,user,row)


@router.put('/projects/{project_id}/uploads/{session_id}/chunks/{index}')
@route_permission('worker.deliver')
async def upload_chunk(project_id:str,session_id:str,index:int,request:Request,
    chunk_sha256:str=Header(alias='X-Chunk-SHA256',pattern='^[0-9a-f]{64}$'),
    user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if request.headers.get('content-type','').split(';')[0]!='application/octet-stream':raise HTTPException(415,'分片必须使用application/octet-stream')
    project,row=current(db,project_id,session_id,user)
    authenticated_version=user.token_version
    uploads.open_session(row);expected=uploads.expected_size(row,index)
    db.commit()  # Never hold a project writer lock while waiting for network bytes.
    incoming=uploads.session_directory(row.id)/('incoming-'+uuid4().hex)
    digest=hashlib.sha256();size=0
    try:
        fd=os.open(incoming,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as target:
            async for block in request.stream():
                size+=len(block)
                if size>expected:raise HTTPException(413,'分片超过声明的文件范围')
                target.write(block);digest.update(block)
            target.flush();os.fsync(target.fileno())
        if size!=expected:raise HTTPException(400,'分片长度不完整，请重发原分片')
        if digest.hexdigest()!=chunk_sha256:raise HTTPException(409,'分片SHA-256不匹配，请重发原分片')
        project,row=current(db,project_id,session_id,user)  # Actor/doc ACL can change while bytes arrive.
        if user.token_version!=authenticated_version:raise HTTPException(401,'账号会话在上传期间已变化，请重新登录')
        result=uploads.store_part(db,project,user,row,index,incoming,chunk_sha256,size)
        db.commit();return result
    except OSError as error:
        db.rollback()
        if error.errno in (errno.ENOSPC,errno.EDQUOT):raise HTTPException(507,'上传临时空间不足，请保留本地原文件稍后续传') from None
        raise
    except Exception:
        db.rollback();raise
    finally:incoming.unlink(missing_ok=True)


@router.post('/projects/{project_id}/uploads/{session_id}/finish')
@route_permission('worker.deliver')
def finish_upload(project_id:str,session_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project,row=current(db,project_id,session_id,user)
    try:
        uploads.finish(db,project,user,row)
        db.commit()
    except Exception:
        db.rollback();raise
    uploads.discard_parts(row)
    return uploads.finished_result(db,project,user,row)


@router.delete('/projects/{project_id}/uploads/{session_id}')
@route_permission('worker.deliver')
def cancel_upload(project_id:str,session_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project,row=current(db,project_id,session_id,user,write=False,context=False)
    if row.state=='finished':raise HTTPException(409,'上传已经完成，不能通过取消会话删除真实附件')
    if row.state!='cancelled':
        row.state='cancelled';row.updated_at=utcnow()
        log_change(db,project.id,'upload_session',row.id,'cancel',user.id,'取消未完成的文件上传',None,{'client_uuid':row.client_uuid})
    db.commit();uploads.discard_parts(row)
    return {'state':'cancelled'}
