from datetime import date
"""One project document checklist; evidence submission always binds a real local file."""
import json
from urllib.parse import quote
from typing import Literal, Annotated
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, StrictBool, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User, VehicleUnit, DocumentVersion, DocumentTemplateFile
from app.services import project_documents as docs
from app.services.document_requirements import RequirementInput, read_asset
from app.services.scope import ensure_project_visible
from app.services.permissions import C_PLAN
from app.services.system_permissions import route_permission
from app.services.change_log import log_change
from app.services.upload_safety import read_upload_limited
from app.services.optimistic import require_client_version
from app.services.rate_limit import rate_limit_export
from app.config import MAX_UPLOAD_SIZE
from app.time_utils import utcnow

def _private_response(response:Response):
    response.headers['Cache-Control']='private, no-store'


router=APIRouter(prefix='/projects',tags=['项目资料'],dependencies=[Depends(_private_response)])


class DispatchConfirmation(BaseModel):
    model_config = {'extra': 'forbid'}
    conclusion: Literal['not_ready', 'risky', 'ready']
    notes: str = Field(default='', max_length=4000)
    review_token: str = Field(min_length=64, max_length=64, pattern='^[a-f0-9]{64}$')


@router.post('/{project_id}/documents/dispatch-review')
@route_permission('project.manage_plan')
def preview_dispatch(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.dispatch_review import manifest, visible_manifest
    from app.services.permissions import authorize_project
    from app.services.project_lifecycle import ensure_project_writable
    project = ensure_project_visible(db, project_id, user)
    authorize_project(user, project, C_PLAN); ensure_project_writable(project)
    result = visible_manifest(db, project, user, manifest(db, project))
    # T26 permits only audit writes while reading; no business state is created.
    from app.models import ProjectDocument, ProjectDocumentDefinition
    shown = [item for key in ('met','not_applicable','unmet') for item in result[key] if not item.get('restricted')]
    document_ids = {item['id'] for item in shown if item['kind']=='document'}
    definition_ids = {item['definition_id'] for item in shown if item['kind']=='definition'}
    docs.audit_access(db, project, user,
        documents=db.query(ProjectDocument).filter(ProjectDocument.id.in_(document_ids)).all() if document_ids else [],
        definitions=db.query(ProjectDocumentDefinition).filter(ProjectDocumentDefinition.id.in_(definition_ids)).all() if definition_ids else [])
    db.commit()
    return result


@router.post('/{project_id}/documents/dispatch-review/confirm')
@route_permission('project.manage_plan')
def confirm_dispatch(project_id: str, body: DispatchConfirmation, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.dispatch_review import confirm, summary
    project = docs.writable(db, project_id, user, C_PLAN)
    confirm(db, project, user, **body.model_dump())
    db.commit()
    return {'message': '发车前资料确认已记录', 'summary': summary(db, project)}


@router.get('/{project_id}/documents/dispatch-review/history')
@route_permission('project.read')
def dispatch_history(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.dispatch_review import history
    project = ensure_project_visible(db, project_id, user)
    return history(db, project, user)


class ProjectRequirementInput(RequirementInput):
    owner_id:str|None=Field(default=None,max_length=36)


class OwnerChange(BaseModel):
    model_config={'extra':'forbid'}
    owner_id:str|None=Field(...,max_length=36)
    version:int|None=Field(default=None,ge=1)


class Selection(BaseModel):
    model_config={'extra':'forbid'}
    document_ids:list[str]=Field(min_length=1,max_length=100)
    attachment_id:str=Field(min_length=1,max_length=36)
    note:str=Field(default='',max_length=5000)
    milestone_dates:dict[str,date]=Field(default_factory=dict)

    @field_validator('document_ids')
    @classmethod
    def identities(cls,value):
        if len(set(value))!=len(value) or any(not key.strip() or len(key)>36 for key in value):
            raise ValueError('资料ID必须是不同的非空字符串')
        return value


class StateChange(BaseModel):
    model_config={'extra':'forbid'}
    status:Literal['pending','waived']
    reason:str=Field(min_length=1,max_length=5000)
    version:int|None=Field(default=None,ge=1)


class Review(BaseModel):
    model_config={'extra':'forbid'}
    decision:Literal['approved','rejected']
    note:str=Field(default='',max_length=5000)


class GeneratedNote(BaseModel):
    model_config={'extra':'forbid'}
    note:str=Field(default='',max_length=5000)
    confidential:StrictBool=False
    confidential_user_ids:list[str]=Field(default_factory=list,max_length=200)


class GeneratedContact(GeneratedNote):
    application_id:str=Field(min_length=1,max_length=36)


def one_document(db,project,user,identity):
    return next(row for row in docs.view(db,project,user)['documents'] if row['id']==identity)


def one_definition(db,project,user,identity):
    return next(row for row in docs.view(db,project,user)['definitions'] if row['id']==identity)


@router.get('/{project_id}/documents')
@route_permission('project.read')
def list_documents(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db),vehicle_unit_id:Annotated[str|None,Query(min_length=1,max_length=36)]=None):
    project=ensure_project_visible(db,project_id,user)
    if vehicle_unit_id is not None:
        unit=db.get(VehicleUnit,vehicle_unit_id)
        if unit is None or unit.project_id!=project_id:
            raise HTTPException(404,'车辆档案不存在')
    return docs.view(db,project,user,vehicle_unit_id=vehicle_unit_id,audit=True)


class ConfidentialityChange(BaseModel):
    model_config={'extra':'forbid'}
    confidential:StrictBool
    confidential_user_ids:list[str]=Field(default_factory=list,max_length=200)
    version:int=Field(ge=1,strict=True)

    @field_validator('confidential_user_ids')
    @classmethod
    def people(cls,value):
        if len(set(value))!=len(value) or any(not key.strip() or len(key)>36 for key in value):
            raise ValueError('指定人员必须是不同的有效账号ID')
        return value


@router.get('/{project_id}/documents/confidentiality-members')
@route_permission('project.read')
def confidentiality_members(project_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=ensure_project_visible(db,project_id,user)
    if user.id!=project.manager:raise HTTPException(403,'仅项目负责人可管理保密可见人员')
    return [{'id':row.id,'display_name':row.display_name,'role':row.role} for row in docs.confidentiality_members(db,project) if row.id!=project.manager]


@router.put('/{project_id}/documents/{document_id}/confidentiality')
@route_permission('project.manage_plan')
def document_confidentiality(project_id:str,document_id:str,body:ConfidentialityChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,C_PLAN)
    row=docs.owned_document(db,project.id,document_id)
    docs.change_confidentiality(db,project,user,row,confidential=body.confidential,user_ids=body.confidential_user_ids,expected=body.version)
    db.commit();return one_document(db,project,user,row.id)


@router.put('/{project_id}/documents/requirements/{definition_id}/confidentiality')
@route_permission('project.manage_plan')
def definition_confidentiality(project_id:str,definition_id:str,body:ConfidentialityChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,C_PLAN)
    row=docs.owned_definition(db,project.id,definition_id)
    docs.change_confidentiality(db,project,user,row,confidential=body.confidential,user_ids=body.confidential_user_ids,expected=body.version)
    db.commit();return one_definition(db,project,user,row.id)


@router.put('/{project_id}/documents/files/{attachment_id}/confidentiality')
@route_permission('project.manage_plan')
def file_confidentiality(project_id:str,attachment_id:str,body:ConfidentialityChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.models import Attachment
    project=docs.writable(db,project_id,user,C_PLAN)
    row=db.query(Attachment).filter_by(id=attachment_id,project_id=project.id).populate_existing().first()
    if row is None:raise HTTPException(404,'文件不存在或不属于当前项目')
    docs.change_confidentiality(db,project,user,row,confidential=body.confidential,user_ids=body.confidential_user_ids,expected=body.version)
    db.commit();return docs.file_dict(row)


@router.post('/{project_id}/documents/requirements')
@route_permission('project.manage_plan')
def create_requirement(project_id:str,body:ProjectRequirementInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,C_PLAN)
    row=docs.save_definition(db,project,body,user)
    db.commit();return one_definition(db,project,user,row.id)


@router.put('/{project_id}/documents/requirements/{definition_id}')
@route_permission('project.manage_plan')
def update_requirement(project_id:str,definition_id:str,body:ProjectRequirementInput,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,C_PLAN)
    row=docs.save_definition(db,project,body,user,definition_id)
    db.commit();return one_definition(db,project,user,row.id)


@router.get('/{project_id}/documents/requirements/{definition_id}/blank-file')
@route_permission('project.read')
def blank_file(project_id:str,definition_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=ensure_project_visible(db,project_id,user)
    definition=docs.owned_definition(db,project_id,definition_id)
    if not docs.can_read_definition(user,project,definition):
        raise HTTPException(403,'没有该保密资料模板的查看权限')
    asset=db.get(DocumentTemplateFile,definition.blank_file_id) if definition.blank_file_id else None
    if asset is None:raise HTTPException(404,'尚未上传空白模板')
    if not docs.can_read_blank(db,user,asset,project):raise HTTPException(403,'没有该保密空白模板的查看权限')
    content=read_asset(asset)
    from app.models import ProjectDocumentDefinition, ProjectDocument
    docs.audit_access(db,project,user,
        definitions=db.query(ProjectDocumentDefinition).filter_by(project_id=project.id,blank_file_id=asset.id).all(),
        documents=db.query(ProjectDocument).filter_by(project_id=project.id,blank_file_id=asset.id).all(),action='confidential_dl');db.commit()
    return Response(content,media_type=asset.content_type,
        headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(asset.filename),'Cache-Control':'private, no-store'})


@router.get('/{project_id}/documents/files')
@route_permission('project.read')
def list_files(project_id:str,entity_type:str|None=None,entity_id:str|None=None,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.models import Attachment
    project=ensure_project_visible(db,project_id,user)
    query=db.query(Attachment).filter_by(project_id=project_id)
    if entity_type is not None:query=query.filter_by(entity_type=entity_type)
    if entity_id is not None:query=query.filter_by(entity_id=entity_id)
    assets=query.order_by(Attachment.uploaded_at.desc(),Attachment.id).all()
    users={row.id:row.display_name for row in db.query(User).filter(User.id.in_({asset.uploaded_by for asset in assets}))}
    visible=[asset for asset in assets if docs.can_read_file(user,project,asset)]
    docs.audit_access(db,project,user,files=visible);db.commit()
    return [docs.file_dict(asset,users) for asset in visible]


@router.post('/{project_id}/documents/files')
@route_permission('worker.deliver')
async def upload_file(project_id:str,file:UploadFile=File(...),document_ids:str=Form(default='[]'),note:str=Form(default=''),
    entity_type:str=Form(default='project'),entity_id:str=Form(default=''),category:str=Form(default=''),milestone_dates:str=Form(default='{}'),
    confidential:bool=Form(default=False),confidential_user_ids:str=Form(default='[]'),
    user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    try:
        identities=json.loads(document_ids)
        if not isinstance(identities,list) or len(identities)>100 or any(not isinstance(value,str) or not value.strip() or len(value)>36 for value in identities) or len(set(identities))!=len(identities):
            raise ValueError
    except (ValueError,TypeError):raise HTTPException(400,'资料选择必须是最多100个不同ID的数组') from None
    if len(note)>5000:raise HTTPException(400,'版本说明过长')
    try:
        raw_dates = json.loads(milestone_dates) if len(milestone_dates) <= 1000 else None
        if not isinstance(raw_dates, dict) or len(raw_dates) > 7:
            raise ValueError
        dates = {key: date.fromisoformat(value) for key, value in raw_dates.items()}
        if any(day.isoformat() != raw_dates[key] for key, day in dates.items()):
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(400, '签单日期必须是事件与YYYY-MM-DD日期的映射') from None
    project=docs.writable(db,project_id,user,'worker.deliver')
    try:people=json.loads(confidential_user_ids)
    except (ValueError,TypeError):raise HTTPException(400,'附件可见人员必须是JSON数组') from None
    docs.validate_upload_policy(db,project,user,confidential=confidential,user_ids=people)
    pending_before = {identity for identity in identities if docs.owned_document(db,project_id,identity).status == 'pending'}
    data=await read_upload_limited(file,MAX_UPLOAD_SIZE)
    try:
        asset=docs.create_attachment(db,project,data,file.filename,file.content_type,user,entity_type=entity_type,entity_id=entity_id,category=category)
        docs.apply_upload_confidentiality(db,project,user,asset,confidential=confidential,user_ids=people)
        if identities:docs.submit(db,project,identities,asset.id,user,note)
        from app.services.project_events import record_document_dates
        record_document_dates(db, project, identities, asset.id, dates, user.id, pending_ids=pending_before)
        db.commit()
        result=docs.view(db,project,user)
        return {'file':docs.file_dict(asset,{user.id:user.display_name}),'documents':[row for row in result['documents'] if row['id'] in identities]}
    except Exception:
        db.rollback();raise


@router.post('/{project_id}/documents/submit')
@route_permission('worker.deliver')
def submit(project_id:str,body:Selection,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,'worker.deliver')
    pending_before = {identity for identity in body.document_ids if docs.owned_document(db,project_id,identity).status == 'pending'}
    docs.submit(db,project,body.document_ids,body.attachment_id,user,body.note)
    from app.services.project_events import record_document_dates
    record_document_dates(db, project, body.document_ids, body.attachment_id, body.milestone_dates, user.id, pending_ids=pending_before)
    db.commit();return {'documents':[row for row in docs.view(db,project,user)['documents'] if row['id'] in body.document_ids]}


@router.put('/{project_id}/documents/{document_id}')
@route_permission('worker.deliver')
def change_state(project_id:str,document_id:str,body:StateChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,'worker.deliver')
    row=docs.owned_document(db,project_id,document_id)
    docs.update_state(db,project,row,user,body.status,body.reason,require_client_version(body.version))
    db.commit();return one_document(db,project,user,row.id)


@router.put('/{project_id}/documents/{document_id}/owner')
@route_permission('project.manage_plan')
def assign_owner(project_id:str,document_id:str,body:OwnerChange,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.document_deadlines import validate_owner
    from app.services.optimistic import bump_version, require_client_version
    project=docs.writable(db,project_id,user,C_PLAN)
    row=docs.owned_document(db,project_id,document_id)
    if not docs.can_read_document(user,project,row):raise HTTPException(403,'无权指派该保密资料')
    validate_owner(db,project,body.owner_id)
    before=row.owner_id
    bump_version(row,require_client_version(body.version),db=db)
    row.owner_id=body.owner_id
    log_change(db,project.id,'project_document',row.id,'assign_owner',user.id,'指派资料负责人',{'owner_id':before},{'owner_id':body.owner_id})
    db.commit();return one_document(db,project,user,row.id)


@router.post('/{project_id}/documents/{document_id}/versions/{version_id}/review')
@route_permission('project.manage_plan')
def review(project_id:str,document_id:str,version_id:str,body:Review,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    project=docs.writable(db,project_id,user,C_PLAN)
    row=docs.owned_document(db,project_id,document_id)
    if not docs.can_read_document(user,project,row):raise HTTPException(403,'无权审核该保密资料')
    version=db.get(DocumentVersion,version_id)
    if version is None or version.project_document_id!=row.id:raise HTTPException(404,'资料版本不存在')
    from app.models import Attachment
    asset=db.get(Attachment,version.attachment_id)
    if asset is None or asset.project_id!=project.id:raise HTTPException(404,'资料原件不存在')
    if not docs.can_read_file(user,project,asset):raise HTTPException(403,'无权审核该保密附件版本')
    if version.uploaded_by == user.id:
        raise HTTPException(400,'该版本由你提交，不能自己审核，请由其他获授权人员复核')
    if body.decision=='rejected' and not body.note.strip():raise HTTPException(400,'退回意见必须说明原因')
    metadata=dict(version.review_metadata or {})
    review={'decision':body.decision,'note':body.note.strip(),'by':user.id,'at':docs.iso(utcnow())}
    metadata['review_history']=[*(metadata.get('review_history') or []),review]
    metadata['latest_review']=review;version.review_metadata=metadata
    log_change(db,project.id,'document_version',version.id,'review',user.id,f'资料版本审核：{row.name}',None,review)
    if version.uploaded_by:
        from app.routers.notifications import notify
        notify(db,version.uploaded_by,f'资料评审意见：{row.name}'[:200],body.note.strip() or '资料版本已复核',ntype='document_reviewed',project_id=project.id,entity_id=row.id)
    db.commit();return next(value for value in one_document(db,project,user,row.id)['versions'] if value['id']==version.id)


@router.get('/{project_id}/documents/{document_id}/versions/{version_id}/download')
@route_permission('project.read')
def download_version(project_id:str,document_id:str,version_id:str,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.models import Attachment
    project=ensure_project_visible(db,project_id,user);document=docs.owned_document(db,project_id,document_id)
    version=db.get(DocumentVersion,version_id)
    if version is None or version.project_document_id!=document.id:raise HTTPException(404,'资料版本不存在')
    asset=db.get(Attachment,version.attachment_id)
    if asset is None or asset.project_id!=project_id:raise HTTPException(404,'附件不存在')
    if not docs.can_read_document(user,project,document) or not docs.can_read_file(user,project,asset):raise HTTPException(403,'没有该保密资料的下载权限')
    path=docs.validate_file(asset)
    docs.audit_access(db,project,user,documents=[document],files=[asset],action='confidential_dl');db.commit()
    return FileResponse(path,filename=asset.filename,media_type=asset.content_type,
        headers={'Cache-Control':'private, no-store'})


@router.post('/{project_id}/documents/{document_id}/generate-inventory')
@route_permission('worker.deliver')
def generate_inventory(project_id:str,document_id:str,body:GeneratedNote=GeneratedNote(),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return _generate_form(db,project_id,document_id,user,body,'inventory')


@router.post('/{project_id}/documents/{document_id}/generate-lifecycle')
@route_permission('worker.deliver')
def generate_lifecycle(project_id:str,document_id:str,body:GeneratedNote=GeneratedNote(),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return _generate_form(db,project_id,document_id,user,body,'lifecycle')


@router.post('/{project_id}/documents/{document_id}/generate-contact')
@route_permission('worker.deliver')
def generate_contact(project_id:str,document_id:str,body:GeneratedContact,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return _generate_form(db,project_id,document_id,user,body,'contact',application_id=body.application_id)


def _generate_form(db,project_id,document_id,user,body,kind,**kwargs):
    from app.services.generated_document_forms import generate
    project=docs.writable(db,project_id,user,'worker.deliver');document=docs.owned_document(db,project_id,document_id)
    try:
        generate(db,project,document,user,body,kind,**kwargs)
        db.commit();return one_document(db,project,user,document.id)
    except Exception:
        db.rollback();raise


@router.get('/{project_id}/documents/{document_id}/generation-sources')
@route_permission('worker.deliver')
def generation_sources(project_id:str,document_id:str,confidential:bool=False,
    confidential_user_ids:list[str]=Query(default=[],max_length=200),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    from app.services.generated_document_forms import contact_sources
    project=ensure_project_visible(db,project_id,user)
    if not docs.can_submit(user,project):raise HTTPException(403,'当前没有资料提交权限')
    document=docs.owned_document(db,project_id,document_id)
    result,assets=contact_sources(db,project,document,user,GeneratedNote(confidential=confidential,confidential_user_ids=confidential_user_ids))
    docs.audit_access(db,project,user,files=assets);db.commit()
    return result


class PackageSelection(BaseModel):
    model_config = {'extra': 'forbid'}
    document_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator('document_ids')
    @classmethod
    def unique_ids(cls, values):
        if len(set(values)) != len(values) or any(not value.strip() or len(value) > 36 for value in values):
            raise ValueError('请选择不同的非空资料ID')
        return values


@router.post('/{project_id}/documents/package')
@route_permission('project.export')
def package_documents(project_id: str, body: PackageSelection, user: User = Depends(rate_limit_export()), db: Session = Depends(get_db)):
    from app.services.permissions import authorize_project, C_EXPORT
    from app.services.document_packages import selected_package, chunks
    from app.routers.io_routes import _export_content_disposition
    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask
    project = ensure_project_visible(db, project_id, user)
    authorize_project(user, project, C_EXPORT)
    package = selected_package(db, project, user, body.document_ids)
    return StreamingResponse(chunks(package), media_type='application/zip', background=BackgroundTask(package.close),
        headers={'Content-Disposition': _export_content_disposition(project.name + '-所选资料', 'zip'),
                 'Cache-Control': 'private, no-store'})
