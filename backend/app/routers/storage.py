"""Storage visibility and an explicit preview/confirm retention boundary."""
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models import User,FileCleanupReceipt
from app.services import project_documents as docs,storage_cleanup,storage_usage
from app.services.scope import ensure_project_visible
from app.services.system_permissions import route_permission,has_permission
from app.services.permissions import C_UPDATE

def private_response(response:Response):response.headers['Cache-Control']='private, no-store'
router=APIRouter(tags=['存储管理'],dependencies=[Depends(private_response)])

class CleanupPolicy(BaseModel):
    model_config={'extra':'forbid'}
    keep_periods:int=Field(default=8,ge=1,le=520,strict=True)

class CleanupConfirm(CleanupPolicy):
    fingerprint:str=Field(pattern='^[0-9a-f]{64}$')
    reason:str=Field(min_length=1,max_length=1000)


@router.get('/system/storage')
@route_permission('system.backups.read')
def global_storage(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if not has_permission(user,'system.backups.read'):raise HTTPException(403,'没有系统存储统计查看权限')
    return storage_usage.global_usage(db,user)


@router.get('/projects/{project_id}/storage')
@route_permission('project.read')
def project_storage(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return storage_usage.project_usage(db,ensure_project_visible(db,project_id,user),user)


@router.post('/projects/{project_id}/storage/cleanup-preview')
@route_permission('project.update')
def preview_cleanup(project_id:str,body:CleanupPolicy,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,C_UPDATE)
    preview=storage_cleanup.build_preview(db,project,user,body.keep_periods)[0]
    # A public preview is pure; an actual authorized private-file metadata view
    # receives T26's access audit without changing rules, evidence or its hash.
    from app.models import Attachment
    identities={row['attachment_id'] for row in [*preview['candidates'],*preview['protected']]}
    docs.audit_access(db,project,user,files=db.query(Attachment).filter(Attachment.id.in_(identities)).all())
    db.commit()
    return preview


@router.post('/projects/{project_id}/storage/cleanup-confirm')
@route_permission('project.update')
def confirm_cleanup(project_id:str,body:CleanupConfirm,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,C_UPDATE)
    try:
        result=storage_cleanup.apply_cleanup(db,project,user,body.keep_periods,body.fingerprint,body.reason)
        db.commit()
    except Exception:
        db.rollback();raise
    receipt=db.get(FileCleanupReceipt,result['receipt_id']);pending=0
    for candidate in receipt.policy['candidates']:
        path=storage_cleanup.trash_directory()/(candidate['removal_record_id']+'.bin')
        if path.is_file():pending+=path.stat().st_size
    return {**result,'released_bytes':result['removed_bytes']-pending,'pending_reclaim_bytes':pending,
        'warning':'原件访问已移除，部分磁盘回收等待重试，元数据与授权凭据已保留' if pending else None}
