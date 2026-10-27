"""Previewed weekly retention, durable provenance and recoverable filesystem moves."""
from collections import defaultdict
from datetime import datetime,date,time,timedelta,timezone
from pathlib import Path
from uuid import uuid4,UUID
from zoneinfo import ZoneInfo
import hashlib,json,os,logging
from sqlalchemy import select,event
from fastapi import HTTPException
from app import config,models
from app.db import Base
from app.services import project_documents as docs
from app.services.file_retention import IDENTITY,series,periods_kept,removal_record
from app.services.project_retention import _row
from app.services.resumable_uploads import digest_file
from app.services.change_log import log_change
from app.services.permissions import authorize_project,C_UPDATE
from app.time_utils import utcnow


def _iso(value):return value.isoformat() if isinstance(value,(datetime,date)) else value
def _hash(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=_iso).encode()).hexdigest()


def milestone_protection(db,project,documents,versions):
    """Consume T20/T28's precision contract, including derived arrival_all dates."""
    from app.services.project_events import events_for_project
    by_id={row.id:row for row in documents};groups=defaultdict(list)
    for version in versions:
        document=by_id.get(version.project_document_id)
        if document:groups[series(document)].append(version)
    protected={};facts=[]
    for fact in events_for_project(db,project):
        source=fact.get('actual_source') or {}
        for identity in source.get('document_version_ids',[]):protected[identity]='签单直接关联版本'
        if not fact.get('actual_at') and not fact.get('actual_date'):continue
        key=fact['event_key'];precision=fact.get('actual_precision')
        legacy=source.get('kind')=='legacy_status_transition'
        facts.append({'event_key':key,'precision':precision,'basis':source.get('time_basis') or ('实际日期' if precision=='date' else '实际时刻')})
        if legacy:
            for version in versions:protected[version.id]='旧状态审计补登尚无可核实业务日期，相关周次保守保留'
            continue
        if precision=='date' or key=='arrival_all':
            day=date.fromisoformat(fact['actual_date'])
            start=datetime.combine(day,time.min,ZoneInfo(project.timezone or 'Asia/Shanghai')).astimezone(timezone.utc).replace(tzinfo=None)
            end=datetime.combine(day+timedelta(days=1),time.min,ZoneInfo(project.timezone or 'Asia/Shanghai')).astimezone(timezone.utc).replace(tzinfo=None)
            year,week,_=day.isocalendar();period=f'{year:04}-W{week:02}'
            for version in versions:
                document=by_id.get(version.project_document_id)
                if document and document.period_key==period:protected[version.id]='实际日期所在现场周次（日期精度）'
        else:
            start=datetime.fromisoformat(fact['actual_at']).astimezone(timezone.utc).replace(tzinfo=None)
            end=start;period=None
        for rows in groups.values():
            dated=[row for row in rows if row.uploaded_at is not None]
            before=max((row.uploaded_at for row in dated if row.uploaded_at<start),default=None)
            after=min((row.uploaded_at for row in dated if row.uploaded_at>=end),default=None)
            for row in rows:
                if row.uploaded_at is None:protected[row.id]='原版本记录时间未知，无法确认里程碑保护'
                elif row.uploaded_at in (before,after) or start<=row.uploaded_at<=end:
                    protected[row.id]='已登记里程碑当日及最近前后版本' if precision=='date' or key=='arrival_all' else '已登记里程碑最近前后版本'
    return protected,facts


def _references(db,assets):
    """Every real owner protects bytes; metadata-only upload receipts are not owners."""
    ids={row.id for row in assets};stored={row.stored_name for row in assets};protected=defaultdict(list);evidence=[];owners=defaultdict(list)
    for row in assets:owners[row.stored_name].append(row)
    for table in Base.metadata.sorted_tables:
        if table.name in ('attachments','document_versions','upload_sessions','file_removal_records'):continue
        for column in table.columns:
            if not any(fk.target_fullname=='attachments.id' for fk in column.foreign_keys):continue
            rows=db.execute(select(*table.primary_key.columns,column).where(column.in_(ids))).all()
            for row in rows:
                protected[row[-1]].append('仍有其它业务记录引用')
                evidence.append([table.name,column.name,*row])
    # These retained business links intentionally predate FK constraints.
    # Match actual Attachment IDs, never human filenames or inferred projects.
    for model,label in ((models.VehicleLifecycleEvent,'车辆问题履历'),(models.ArchiveChecklist,'历史归档清单'),(models.AcceptanceRecord,'验收记录')):
        for row in db.query(model.id,model.project_id,model.attachment_id).filter(model.attachment_id.in_(ids)):
            protected[row.attachment_id].append(f'仍由{label}引用')
            evidence.append([model.__tablename__,'attachment_id',row.id,row.project_id,row.attachment_id])
    for model in (models.DocumentTemplateFile,models.TemplateDoc):
        for row in db.query(model).filter(model.stored_name.in_(stored)):
            for asset in owners[row.stored_name]:protected[asset.id].append('仍由模板文件或参考文档拥有')
            evidence.append([model.__tablename__,row.id,row.stored_name])
    for row in db.query(models.Attachment).filter(models.Attachment.stored_name.in_(stored)):
        for asset in owners[row.stored_name]:
            if asset.stored_name==row.stored_name and asset.id!=row.id:
                protected[asset.id].append('存在其它附件原件归属');evidence.append(['attachment_alias',asset.id,row.id,row.project_id])
    for row in db.query(models.Task.id,models.Task.reference_docs).filter(models.Task.reference_docs.isnot(None)):
        for ref in row.reference_docs or []:
            if not isinstance(ref,dict) or ref.get('stored_name') not in stored:continue
            for asset in owners[ref['stored_name']]:protected[asset.id].append('仍由任务参考文档拥有')
            evidence.append(['task_reference',row.id,ref])
    for archive in db.query(models.ProjectArchive):
        for item in (archive.snapshot or {}).get('binary_files',{}).get('manifest',[]):
            if not isinstance(item,dict) or item.get('stored_name') not in stored:continue
            for asset in owners[item['stored_name']]:protected[asset.id].append('仍由保留归档拥有')
            evidence.append(['retained_archive',archive.id,item])
    return protected,evidence


def build_preview(db,project,user,keep_periods=8):
    if not isinstance(keep_periods,int) or isinstance(keep_periods,bool) or not 1<=keep_periods<=520:raise HTTPException(400,'保留周次必须为1–520期')
    documents=db.query(models.ProjectDocument).filter_by(project_id=project.id).order_by(models.ProjectDocument.id).all()
    by_id={row.id:row for row in documents}
    versions=db.query(models.DocumentVersion).filter(models.DocumentVersion.project_document_id.in_(by_id)).order_by(models.DocumentVersion.id).all()
    assets=db.query(models.Attachment).filter_by(project_id=project.id).order_by(models.Attachment.id).all()
    asset_map={row.id:row for row in assets};version_map=defaultdict(list)
    # Include cross-project/inconsistent references too; they always protect.
    all_refs=db.query(models.DocumentVersion,models.ProjectDocument).join(models.ProjectDocument,models.ProjectDocument.id==models.DocumentVersion.project_document_id).filter(models.DocumentVersion.attachment_id.in_(asset_map)).order_by(models.DocumentVersion.id).all()
    for version,document in all_refs:version_map[version.attachment_id].append((version,document))
    kept=periods_kept(documents,keep_periods);milestones,facts=milestone_protection(db,project,documents,versions)
    ownership,other_refs=_references(db,assets)
    people=dict(db.query(models.User.id,models.User.display_name))
    candidates=[];protected=[];physical=[]
    for asset in assets:
        refs=version_map[asset.id]
        weekly=[document for _,document in refs if document.timing_type=='weekly' and document.stage_key!='legacy']
        if not weekly:continue
        visible=docs.can_read_file(user,project,asset)
        reasons=list(ownership[asset.id]);stat=None
        if getattr(asset,'removal_record',None) is not None:
            reasons.append('已按策略清理' if removal_record(asset,db) else '原清理凭据不一致，需管理员核对')
        if asset.entity_type not in ('project','') or asset.entity_id not in ('',project.id):reasons.append('仍作为任务或问题的原始文件')
        for version,document in refs:
            if document.project_id!=project.id or document.timing_type!='weekly' or document.stage_key=='legacy':reasons.append('仍有非旧weekly资料引用')
            if not document.period_key or document.period_key in kept.get(series(document),set()):reasons.append('最新/当前期或最近保留周次')
            if document.period_key:
                from app.services.document_deadlines import period_start
                try:period_start(document.period_key)
                except (ValueError,HTTPException):reasons.append('周次标识异常，保守保留')
            if version.id in milestones:reasons.append(milestones[version.id])
            if version.uploaded_at is None:reasons.append('原版本记录时间未知，保守保留')
            if not docs.can_read_document(user,project,document):reasons.append('当前账号无该资料的完整查看权限')
        if not visible:reasons.append('当前账号无文件家族查看权限')
        path=config.UPLOAD_DIR/asset.stored_name
        try:
            safe=path.parent.resolve()==config.UPLOAD_DIR.resolve() and Path(asset.stored_name).name==asset.stored_name and not path.is_symlink()
            if not safe or not path.is_file():
                if removal_record(asset,db) is None:reasons.append('普通原件缺失或路径无效，不能作为策略清理')
            else:
                value=path.stat();stat=[value.st_size,value.st_mtime_ns,value.st_ino,value.st_dev]
                if value.st_size!=asset.file_size:reasons.append('原件长度与元数据不一致')
        except OSError:reasons.append('原件暂不可读取')
        physical.append([asset.id,stat])
        if reasons:
            if visible:protected.append({'attachment_id':asset.id,'filename':asset.filename,'reason':'；'.join(dict.fromkeys(reasons))})
            continue
        sha=asset.sha256
        if not sha:
            try:sha,_=digest_file(path)
            except OSError:raise HTTPException(409,'候选原件不可读取，请重新核对存储') from None
        proof=[{'id':version.id,'document_id':document.id,'uploaded_at':docs.iso(version.uploaded_at),
                'uploaded_by':version.uploaded_by,'uploaded_by_name':people.get(version.uploaded_by,'原提交人'),
                'document_status':document.status,'identity':{key:getattr(document,key) for key in IDENTITY}} for version,document in refs]
        candidates.append({'attachment_id':asset.id,'filename':asset.filename,'stored_name':asset.stored_name,'file_size':asset.file_size,
            'sha256':sha,'versions':proof,'documents':[{'id':document.id,'code':document.code,'name':document.name,'period_key':document.period_key} for _,document in refs]})
    evidence={'project':_row(project),'actor':[user.id,user.role,user.permission_version,user.token_version],
        'documents':[_row(row) for row in documents],'versions':[_row(row) for row in versions],
        'attachments':[_row(row) for row in assets],'all_refs':[[_row(version),_row(document)] for version,document in all_refs],
        'events':[_row(row) for row in db.query(models.ProjectEvent).filter_by(project_id=project.id).order_by(models.ProjectEvent.id)],
        'other_references':sorted(other_refs,key=lambda row:json.dumps(row,sort_keys=True,default=_iso)),'physical':physical,'keep_periods':keep_periods,'candidates':candidates,'protected':protected}
    fingerprint=_hash(evidence)
    public=[{key:value for key,value in row.items() if key!='stored_name'} for row in candidates]
    return {'project_id':project.id,'keep_periods':keep_periods,'fingerprint':fingerprint,'candidates':public,
        'candidate_bytes':sum(row['file_size'] for row in candidates),'protected':protected,'milestone_protection':facts},candidates


def trash_directory():
    path=config.DATA_DIR/'.storage-trash'
    if path.is_symlink():raise HTTPException(409,'清理暂存目录不可用')
    path.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(path,0o700)
    return path


def _sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def _track_move(db,source,target,journal):
    key='storage_retention_moves'
    if key not in db.info:
        db.info[key]=[]
        def committed(session):
            if session.in_nested_transaction():return
            for original,trash,metadata in session.info[key]:
                try:trash.unlink(missing_ok=True);metadata.unlink(missing_ok=True)
                except OSError:logging.getLogger(__name__).warning('Authorized storage reclaim awaits retry')
            session.info[key].clear()
        def ended(session,transaction):
            if transaction.parent is not None:return
            for original,trash,metadata in session.info[key]:
                try:
                    if trash.exists() and not original.exists():os.replace(trash,original)
                    if not trash.exists():metadata.unlink(missing_ok=True)
                except OSError:logging.getLogger(__name__).error('Uncommitted original restore awaits journal recovery')
            session.info[key].clear()
        event.listen(db,'after_commit',committed);event.listen(db,'after_transaction_end',ended)
    db.info[key].append((source,target,journal))


def apply_cleanup(db,project,user,keep_periods,fingerprint,reason):
    preview,candidates=build_preview(db,project,user,keep_periods)
    if preview['fingerprint']!=fingerprint:raise HTTPException(409,'资料、文件、权限、事件或引用已变化，请重新预览后确认')
    if not reason.strip():raise HTTPException(400,'请填写历史原件清理原因')
    if not candidates:raise HTTPException(400,'没有可按本次策略清理的历史文件')
    actor_version=(user.token_version,user.permission_version)
    paths=[]
    for candidate in candidates:
        asset=db.get(models.Attachment,candidate['attachment_id'])
        path=docs.validate_file(asset,update_hash=True)
        if asset.sha256!=candidate['sha256']:raise HTTPException(409,'原件SHA-256已变化，未执行清理，请重新核对')
        paths.append((asset,path,candidate))
    db.query(models.User.id).filter_by(id=user.id).with_for_update().all();db.refresh(user)
    if (user.token_version,user.permission_version)!=actor_version:raise HTTPException(409,'账号会话或授权在预览确认期间已变化，请重新登录并预览')
    authorize_project(user,project,C_UPDATE)
    if any(not docs.can_read_file(user,project,asset) for asset,_,_ in paths):raise HTTPException(403,'当前已无候选文件完整查看权限，未执行清理')
    now=utcnow();receipt=models.FileCleanupReceipt(project_id=project.id,actor_id=user.id,actor_name=user.display_name,
        keep_periods=keep_periods,reason=reason.strip(),preview_sha256=fingerprint,applied_at=now,
        policy={'kind':'weekly_retention_v1','fingerprint':fingerprint,'candidates':[],'milestone_protection':preview['milestone_protection']})
    db.add(receipt);db.flush();proof=[]
    for asset,path,candidate in paths:
        identity=str(uuid4());directory=trash_directory();trash=directory/(identity+'.bin');journal=directory/(identity+'.json')
        record=models.FileRemovalRecord(id=identity,project_id=project.id,attachment_id=asset.id,receipt_id=receipt.id,
            stored_name=asset.stored_name,filename=asset.filename,sha256=asset.sha256,file_size=asset.file_size,
            removed_at=now,removed_by=user.id,removed_by_name=user.display_name,reason=reason.strip())
        metadata={'stored_name':asset.stored_name,'sha256':asset.sha256,'size':asset.file_size,'project_id':project.id,'attachment_id':asset.id}
        fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as handle:json.dump(metadata,handle,ensure_ascii=False);handle.flush();os.fsync(handle.fileno())
        _sync_directory(directory)
        os.replace(path,trash);_track_move(db,path,trash,journal)
        _sync_directory(directory);_sync_directory(config.UPLOAD_DIR)
        db.add(record);asset.removal_record=record
        proof.append({**candidate,'removal_record_id':identity})
    receipt.policy={**receipt.policy,'candidates':proof}
    log_change(db,project.id,'file_cleanup_receipt',receipt.id,'cleanup',user.id,'按明确预览确认清理旧weekly原件，保留提交事实与元数据',None,
        {'keep_periods':keep_periods,'reason':reason.strip(),'fingerprint':fingerprint,'files':proof})
    db.flush()
    return {'receipt_id':receipt.id,'removed_files':len(candidates),'removed_bytes':preview['candidate_bytes']}


def storage_warnings(db,project,user,vehicle_unit_id=None):
    documents=db.query(models.ProjectDocument).filter_by(project_id=project.id).all()
    versions=db.query(models.DocumentVersion).filter(models.DocumentVersion.project_document_id.in_([row.id for row in documents])).all()
    protected,_=milestone_protection(db,project,documents,versions)
    relevant={row.id for row in documents if vehicle_unit_id is None or row.vehicle_unit_id==vehicle_unit_id}
    assets={row.id:row for row in db.query(models.Attachment).filter(models.Attachment.id.in_([row.attachment_id for row in versions if row.id in protected and row.project_document_id in relevant]))}
    result=[]
    for version in versions:
        if version.id not in protected:continue
        if version.project_document_id not in relevant:continue
        asset=assets.get(version.attachment_id)
        if asset is not None and removal_record(asset,db) and docs.can_read_file(user,project,asset):
            record=removal_record(asset,db)
            result.append(f'{asset.filename}：当前里程碑关联的旧期资料已于{record.removed_at.date()}按当时授权策略清理，原字节不可再下载，完整元数据与清理凭据仍保留。')
    return list(dict.fromkeys(result))


def recover_journals(db):
    """A crash before DB commit restores original bytes; committed moves reclaim."""
    restored=removed=0;purged={}
    directory=config.DATA_DIR/'.storage-trash'
    if not directory.exists() or directory.is_symlink():return {'restored':0,'reclaimed':0}
    def recovery_order(path):
        try:
            if path.is_symlink() or path.stat().st_size>4096:return '',path.name
            return str(json.loads(path.read_text()).get('project_id','')),path.name
        except (ValueError,OSError,TypeError,AttributeError):return '',path.name
    for journal in sorted(directory.glob('*.json'),key=recovery_order):
        try:
            if journal.is_symlink() or journal.stat().st_size>4096:continue
            identity=journal.stem
            if str(UUID(identity))!=identity:continue
            metadata=json.loads(journal.read_text());stored=metadata['stored_name']
            if not isinstance(stored,str) or Path(stored).name!=stored or '\\' in stored:continue
            trash=journal.with_suffix('.bin');original=config.UPLOAD_DIR/stored
            if trash.is_symlink() or original.is_symlink():continue
            # A second worker may start while the originating transaction is
            # still active. Wait on its project lock before deciding rollback.
            project=db.get(models.Project,metadata.get('project_id'))
            if project:
                from app.services.record_lock import lock_record
                lock_record(db,project,conflict_detail='项目文件恢复正在等待其它操作')
            if not journal.exists():continue
            record=db.get(models.FileRemovalRecord,identity)
            asset=db.get(models.Attachment,metadata.get('attachment_id'))
            authorized=bool(asset and record and removal_record(asset,db) and record.id==removal_record(asset,db).id)
            if project is None:
                from app.services.storage_purge_evidence import purged_snapshot,contains_removal
                pid=metadata.get('project_id')
                if pid not in purged:purged[pid]=purged_snapshot(db,pid)
                snapshot=purged[pid]
                authorized=bool(snapshot and contains_removal(snapshot,identity,metadata))
                # Never resurrect bytes as new orphans after permanent deletion.
                # Missing/corrupt backup proof leaves the private journal intact.
                if not authorized:continue
            if authorized:
                if trash.exists() and digest_file(trash)!=(metadata['sha256'],metadata['size']):continue
                trash.unlink(missing_ok=True);journal.unlink(missing_ok=True);removed+=1
            elif trash.is_file() and asset is not None:
                if digest_file(trash)!=(metadata['sha256'],metadata['size']):continue
                if original.exists():
                    if digest_file(original)!=(metadata['sha256'],metadata['size']):continue
                    trash.unlink()
                else:os.replace(trash,original)
                journal.unlink(missing_ok=True);restored+=1
                if asset:
                    log_change(db,asset.project_id,'attachment',asset.id,'recover_cleanup',None,
                        '恢复未提交清理事务的原件',None,{'sha256':metadata['sha256'],'file_size':metadata['size']})
            else:journal.unlink(missing_ok=True)
        except (OSError,ValueError,KeyError,TypeError):
            logging.getLogger(__name__).warning('Storage journal recovery requires review: %s',journal.name)
    return {'restored':restored,'reclaimed':removed}
