"""Management stays internal; external reads never accept a business identity."""
from datetime import datetime
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from app.db import get_db, _is_sqlite
from app.deps import get_current_user
from app.models import User, ExternalShare, ExternalAccessLog, ProjectDocument
from app.services import external_shares as shares
from app.services.system_permissions import route_permission, route_permission_exempt
from app.services.rate_limit import _memory_consume, _pg_consume


def private_response(response:Response):
    response.headers['Cache-Control']='private, no-store'


router=APIRouter(tags=['外部查看管理'],dependencies=[Depends(private_response)])
external_router=APIRouter(prefix='/external',tags=['外部只读查看'],dependencies=[Depends(private_response)])
bearer=HTTPBearer(auto_error=False)
Scope=Literal['project_progress','vehicle_progress','signoffs','delivery_documents','selected_documents']


class ShareInput(BaseModel):
    model_config={'extra':'forbid'}
    scopes:list[Scope]=Field(default_factory=lambda:list(shares.DEFAULT_SCOPES),min_length=1,max_length=5)
    document_ids:list[str]=Field(default_factory=list,max_length=100)
    expires_at:datetime

    @field_validator('expires_at')
    @classmethod
    def timezone_required(cls,value):
        if value.tzinfo is None:raise ValueError('有效期必须包含时区')
        return value

    @field_validator('document_ids')
    @classmethod
    def valid_ids(cls,value):
        if any(not identity.strip() or len(identity)>36 for identity in value):raise ValueError('资料ID无效')
        return value


class RevokeInput(BaseModel):
    model_config={'extra':'forbid'}
    version:int=Field(strict=True,ge=1)


@router.get('/projects/{project_id}/external-shares')
@route_permission('project.update')
def list_shares(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=shares.manage(db,project_id,user)
    rows=db.query(ExternalShare).filter_by(project_id=project.id).order_by(ExternalShare.created_at.desc()).all()
    options=[{'id':row.id,'code':row.code,'name':row.name,'vehicle_label':row.vehicle_label,'period_key':row.period_key}
        for row in db.query(ProjectDocument).filter_by(project_id=project.id).order_by(ProjectDocument.code)
        if shares.selectable_document(db,project,row)]
    return {'shares':[shares.summary(row) for row in rows],'document_options':options}


@router.post('/projects/{project_id}/external-shares')
@route_permission('project.update')
def create_share(project_id:str,body:ShareInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=shares.manage(db,project_id,user,lock=True)
    from app.time_utils import utcnow
    if db.query(ExternalShare).filter(ExternalShare.project_id==project.id,ExternalShare.revoked_at.is_(None),ExternalShare.expires_at>utcnow()).count()>=50:
        raise HTTPException(400,'此项目有效分享已达50个，请先撤销不再使用的链接')
    return shares.create(db,project,user,body.scopes,body.document_ids,body.expires_at)


@router.post('/projects/{project_id}/external-shares/{share_id}/revoke')
@route_permission('project.update')
def revoke_share(project_id:str,share_id:str,body:RevokeInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return shares.revoke(db,shares.manage(db,project_id,user,lock=True),user,share_id,body.version)


@router.get('/projects/{project_id}/external-shares/{share_id}/access')
@route_permission('project.update')
def access_logs(project_id:str,share_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db),limit:int=Query(50,ge=1,le=100)):
    project=shares.manage(db,project_id,user)
    if not db.query(ExternalShare).filter_by(project_id=project.id,id=share_id).first():raise HTTPException(404,'分享不存在')
    rows=db.query(ExternalAccessLog).filter_by(project_id=project.id,share_id=share_id).order_by(ExternalAccessLog.occurred_at.desc(),ExternalAccessLog.id).limit(limit).all()
    return [{'id':row.id,'time':shares.iso(row.occurred_at),'ip':row.ip,'action':row.action,
             'resource_id':row.resource_id,'status_code':row.status_code} for row in rows]


def consume(db,request):
    ip=request.client.host if request.client else 'unknown'
    key='ext-'+hashlib.sha256(ip.encode()).hexdigest()[:32]
    try:
        if _is_sqlite:_memory_consume(key,120,60)
        else:_pg_consume(db,key,120,60)
    except HTTPException as exc:
        shares.audit(db,request,'throttle',exc.status_code)
        raise


def external_session(request:Request,credentials:HTTPAuthorizationCredentials|None=Depends(bearer),db:Session=Depends(get_db)):
    consume(db,request)
    try:
        if credentials is None:raise HTTPException(401,shares.UNAVAILABLE)
        return shares.resolve_session(db,credentials.credentials)
    except HTTPException as exc:
        shares.audit(db,request,'authorize',exc.status_code,shares.audit_share(db,credentials.credentials,session=True) if credentials else None)
        raise


@external_router.post('/bootstrap')
@route_permission_exempt('匿名分享凭据仅从请求体核对，换发 external_view 专用短期只读会话；不接受业务Cookie')
async def bootstrap(request:Request,db:Session=Depends(get_db)):
    consume(db,request)
    body=None
    try:
        # A fixed small body prevents arbitrarily large anonymous parsing. Raw
        # secrets and validation bodies are never returned by a schema error.
        chunks=bytearray()
        async for chunk in request.stream():
            if len(chunks)+len(chunk)>512:raise HTTPException(401,shares.UNAVAILABLE)
            chunks.extend(chunk)
        import json
        try:body=json.loads(chunks)
        except (ValueError,UnicodeError):raise HTTPException(401,shares.UNAVAILABLE) from None
        if not isinstance(body,dict) or set(body)!={'token'}:raise HTTPException(401,shares.UNAVAILABLE)
        row,project,token,expires=shares.bootstrap(db,body['token'])
    except HTTPException as exc:
        shares.audit(db,request,'bootstrap',exc.status_code,shares.audit_share(db,body.get('token')) if isinstance(body,dict) else None)
        raise
    result=shares.projection(db,row,project)
    shares.audit(db,request,'bootstrap',200,row)
    return {'session_token':token,'session_expires_at':expires,'view':result}


@external_router.get('/view')
@route_permission_exempt('external_view专用会话+当前分享范围只读投影，不授权业务账号或内部接口')
def view(request:Request,state=Depends(external_session),db:Session=Depends(get_db)):
    row,project=state
    result=shares.projection(db,row,project)
    shares.audit(db,request,'view',200,row)
    return result


@external_router.get('/documents/{document_id}/versions/{version_id}/download')
@route_permission_exempt('专用外部会话逐次核对项目、所选资料、当前最新原件及所有保密引用，下载留痕')
def download(document_id:str,version_id:str,request:Request,state=Depends(external_session),db:Session=Depends(get_db)):
    row,project=state
    try:asset,path=shares.download(db,row,project,document_id,version_id)
    except HTTPException as exc:
        shares.audit(db,request,'download',exc.status_code,row,document_id)
        raise
    shares.audit(db,request,'download',200,row,document_id)
    # Always attachment: user-supplied HTML/SVG is never navigated as a page.
    return FileResponse(path,filename=asset.filename,media_type='application/octet-stream',
        headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer'})
