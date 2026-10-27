"""Actual system forms published through the canonical document evidence seam.

Callers hold the project lock. Private inputs are excluded unless an explicitly
private output proves every possible recipient can read every input.
"""
from dataclasses import dataclass
from datetime import timedelta
from copy import deepcopy
import io
from fastapi import HTTPException
from openpyxl import Workbook
from app import models
from app.services import project_documents as docs,report_forms
from app.services import document_deadlines as deadlines
from app.services.scope import ensure_project_visible
from app.services.change_log import log_change
from app.time_utils import utcnow

XLSX='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
DOCX='application/vnd.openxmlformats-officedocument.wordprocessingml.document'


@dataclass
class Product:
    data:bytes
    filename:str
    mime:str
    source:dict
    source_files:list


def target(project,document,user,kind,now=None):
    if not docs.can_read_document(user,project,document):raise HTTPException(403,'无权生成该保密资料')
    if document.stage_key=='legacy' or document.scope!='project' or not docs.applicable(project,document):
        raise HTTPException(400,'当前资料范围不支持系统生成')
    if kind=='lifecycle':
        if document.code!='6.2' or document.timing_type!='weekly':raise HTTPException(400,'仅每周6.2生命周期表可生成本周文件')
        if document.period_key!=deadlines.period_key(deadlines.local_now(project,now).date()):
            raise HTTPException(409,'仅可生成项目现场时区的当前周资料；历史周次请上传对应真实原件')
    elif kind=='contact':
        if document.code!='6.9.3' or document.timing_type!='on_demand':raise HTTPException(400,'仅6.9.3购买申请单可由内部联系单生成')
    elif kind=='inventory':
        if document.code!='9.2' or document.timing_type!='lifetime':raise HTTPException(400,'仅9.2项目物资收发清单可由流水生成')
    else:raise HTTPException(400,'未知生成方式')


def source_file_readable(db,project,user,asset):
    if asset is None or asset.project_id!=project.id or not docs.can_read_file(user,project,asset):return False
    try:docs.file_path(asset)
    except HTTPException:return False
    # Never attempt to infer another project's policy from an original alias.
    if db.query(models.Attachment.id).filter(models.Attachment.stored_name==asset.stored_name,
            models.Attachment.project_id!=project.id).first():return False
    return True


def _file_allowed(db,project,document,user,asset,options):
    if not source_file_readable(db,project,user,asset):return False
    if not docs.file_is_confidential(asset):return True
    if not options.confidential:return False
    selected=docs.validate_upload_policy(db,project,user,confidential=True,user_ids=options.confidential_user_ids)
    recipients=db.query(models.User).filter(models.User.id.in_([project.manager,*selected])).populate_existing().all()
    # Check the entire independent file scope, including people currently hidden
    # by the target family. A later family grant must not activate a latent copy.
    return all(docs.can_read_file(person,project,asset) for person in recipients)


def _application_sources(db,project):
    """A previous private generated use also constrains regeneration of a form."""
    sources={}
    rows=db.query(models.DocumentVersion,models.Attachment,models.ProjectDocument.code).join(models.Attachment,models.Attachment.id==models.DocumentVersion.attachment_id).join(
        models.ProjectDocument,models.ProjectDocument.id==models.DocumentVersion.project_document_id).filter(models.Attachment.project_id==project.id).all()
    for version,asset,code in rows:
        raw=version.review_metadata if isinstance(version.review_metadata,dict) else {}
        metadata=raw.get('generated') if isinstance(raw.get('generated'),dict) else {}
        ids=metadata.get('source_application_ids')
        if isinstance(ids,list) and ids and all(isinstance(value,str) and value for value in ids):
            for identity in ids:sources.setdefault(identity,[]).append(asset)
        elif code=='6.9.3' and docs.file_is_confidential(asset):
            # Old private Word uploads have no reliable application identity.
            # Do not guess from titles and accidentally regenerate to public.
            sources.setdefault(None,[]).append(asset)
    return sources


def readable_lifecycle(db,project,user):
    """Legacy authenticated download has one recipient: the current actor."""
    events=[];assets=[]
    for row in db.query(models.VehicleLifecycleEvent).filter(models.VehicleLifecycleEvent.project_id==project.id,
            models.VehicleLifecycleEvent.event_type.in_(report_forms._ISSUE_TYPES)).order_by(
                models.VehicleLifecycleEvent.event_date,models.VehicleLifecycleEvent.created_at,models.VehicleLifecycleEvent.id):
        if row.attachment_id:
            asset=db.get(models.Attachment,row.attachment_id)
            if not source_file_readable(db,project,user,asset):continue
            assets.append(asset)
        events.append(row)
    return events,assets


def readable_contact(db,project,user,application_id):
    app=db.get(models.ItemApplication,application_id)
    if app is None or app.project_id!=project.id:raise HTTPException(404,'联系单不存在')
    references=_application_sources(db,project);assets=[*references.get(None,[]),*references.get(app.id,[])]
    if not all(source_file_readable(db,project,user,asset) for asset in assets):raise HTTPException(403,'没有该联系单关联来源的导出权限')
    return assets


def contact_sources(db,project,document,user,options):
    target(project,document,user,'contact')
    docs.validate_upload_policy(db,project,user,confidential=options.confidential,user_ids=options.confidential_user_ids)
    references=_application_sources(db,project);result=[];read=[]
    for row in db.query(models.ItemApplication).filter_by(project_id=project.id).order_by(models.ItemApplication.created_at,models.ItemApplication.id):
        assets=[*references.get(None,[]),*references.get(row.id,[])]
        if not all(_file_allowed(db,project,document,user,asset,options) for asset in assets):continue
        result.append({'id':row.id,'title':row.title,'item_name':row.item_name,'apply_date':docs.iso(row.apply_date),'status':row.status})
        read.extend(assets)
    return result,read


def lifecycle(db,project,document,user,options,now=None):
    target(project,document,user,'lifecycle',now)
    day=deadlines.local_now(project,now).date();start=deadlines.week_start(day);end=start+timedelta(days=7)
    events=[];assets=[]
    for event in db.query(models.VehicleLifecycleEvent).filter(models.VehicleLifecycleEvent.project_id==project.id,
            models.VehicleLifecycleEvent.event_type.in_(report_forms._ISSUE_TYPES),models.VehicleLifecycleEvent.event_date>=start,
            models.VehicleLifecycleEvent.event_date<end).order_by(models.VehicleLifecycleEvent.event_date,models.VehicleLifecycleEvent.created_at,models.VehicleLifecycleEvent.id):
        if event.attachment_id:
            asset=db.get(models.Attachment,event.attachment_id)
            if not _file_allowed(db,project,document,user,asset,options):continue
            assets.append(asset)
        events.append(event)
    period=deadlines.period_key(day)
    data=report_forms.lifecycle_to_excel(db,project.id,events=events,title=f'AGV生命周期表 {period} {start} 至 {end-timedelta(days=1)}')
    return Product(data,f'AGV生命周期表-{period}.xlsx',XLSX,{
        'kind':'lifecycle','period_key':period,'timezone':project.timezone,'start_date':str(start),'end_date':str(end-timedelta(days=1)),
        'time_basis':'原事件event_date，项目现场周一至周日，不改变任何原问题日期',
        'source_event_ids':[row.id for row in events],'source_attachment_ids':list(dict.fromkeys(row.id for row in assets))},assets)


def contact(db,project,document,user,options,application_id):
    choices,assets=contact_sources(db,project,document,user,options)
    if application_id not in {row['id'] for row in choices}:raise HTTPException(404,'联系单不存在或不能用于当前输出范围')
    app=db.get(models.ItemApplication,application_id)
    references=_application_sources(db,project)
    related=list({asset.id:asset for asset in [*references.get(None,[]),*references.get(app.id,[])]}.values())
    return Product(report_forms.item_application_to_docx(db,project.id,app.id),f'内部联系单-{app.id[:8]}.docx',DOCX,
        {'kind':'contact','source_application_ids':[app.id],'source_attachment_ids':[asset.id for asset in related],
         'apply_date':docs.iso(app.apply_date),'time_basis':'原申请日期，空日期保持空白'},related)


def inventory(db,project,document,user,options):
    target(project,document,user,'inventory')
    workbook=Workbook();sheet=workbook.active;sheet.title='物资清单'
    sheet.append(['物品编码','名称','规格','序列号','归属','现存数量','单位','位置','保管人','说明'])
    items={row.id:row for row in db.query(models.ProjectInventoryItem).filter_by(project_id=project.id).order_by(models.ProjectInventoryItem.name,models.ProjectInventoryItem.id)}
    for row in items.values():sheet.append([row.item_code,row.name,row.specification,row.serial_number,row.ownership,row.quantity,row.unit,row.location,row.custodian,row.note])
    history=workbook.create_sheet('收发流水');history.append(['发生时间（按时间依据）','时间依据','物品','动作','数量','结余','原位置','新位置','经手人','说明'])
    movements=db.query(models.ProjectInventoryMovement).filter_by(project_id=project.id).order_by(models.ProjectInventoryMovement.occurred_at,models.ProjectInventoryMovement.id).all()
    from app.services.inventory_time import inventory_time_basis
    for row in movements:
        known_utc=inventory_time_basis(row)=='utc'
        stamp=docs.iso(row.occurred_at) if known_utc else row.occurred_at.isoformat() if row.occurred_at else ''
        history.append([stamp,'utc' if known_utc else row.time_basis or 'legacy_local（历史时区未声明）',items[row.item_id].name if row.item_id in items else row.item_id,row.movement_type,row.quantity,row.balance_after,row.from_location,row.to_location,row.handler,row.note])
    for tab in workbook:
        tab.freeze_panes='A2'
        for cells in tab:
            for cell in cells:
                if isinstance(cell.value,str):cell.data_type='s'
    data=io.BytesIO();workbook.save(data)
    return Product(data.getvalue(),'项目物资收发清单.xlsx',XLSX,{'kind':'inventory','source_item_ids':list(items),'source_movement_ids':[row.id for row in movements],
        'time_basis':'不可变收发流水原发生时间及原time_basis'},[])


def generate(db,project,document,user,options,kind,*,application_id=None):
    token=user.token_version
    target(project,document,user,kind)
    docs.validate_upload_policy(db,project,user,confidential=options.confidential,user_ids=options.confidential_user_ids)
    product=lifecycle(db,project,document,user,options) if kind=='lifecycle' else contact(db,project,document,user,options,application_id) if kind=='contact' else inventory(db,project,document,user,options)
    db.query(models.User.id).filter_by(id=user.id).with_for_update().all();db.refresh(user)
    if not user.is_active or user.token_version!=token:raise HTTPException(401,'账号会话在生成期间已变化，请重新登录')
    ensure_project_visible(db,project.id,user)
    if not docs.can_submit(user,project):raise HTTPException(403,'当前已无资料提交权限')
    target(project,document,user,kind)
    docs.validate_upload_policy(db,project,user,confidential=options.confidential,user_ids=options.confidential_user_ids)
    if not all(_file_allowed(db,project,document,user,asset,options) for asset in product.source_files):raise HTTPException(409,'来源权限在生成期间已变化，请重新生成')
    asset=docs.create_attachment(db,project,product.data,product.filename,product.mime,user,category=document.name)
    docs.apply_upload_confidentiality(db,project,user,asset,confidential=options.confidential,user_ids=options.confidential_user_ids)
    docs.submit(db,project,[document.id],asset.id,user,options.note or '由当前系统记录生成')
    version=db.query(models.DocumentVersion).filter_by(project_document_id=document.id,attachment_id=asset.id).one()
    version.review_metadata={**deepcopy(version.review_metadata or {}),'generated':{**product.source,'generated_at':docs.iso(utcnow()),'generated_by':user.id,'sha256':asset.sha256}}
    docs.audit_access(db,project,user,files=product.source_files,action='confidential_export')
    log_change(db,project.id,'document_version',version.id,'generate',user.id,f'由系统生成资料：{document.code} {document.name}',None,version.review_metadata['generated'])
    db.flush();return document
