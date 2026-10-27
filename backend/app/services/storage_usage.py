"""Resource totals are separate from permission-filtered project file details."""
import os
from pathlib import Path
from app import config,models
from app.services import project_documents as docs
from app.services.file_retention import removal_record
from app.services.permissions import project_capabilities,C_UPDATE
from app.services.storage_cleanup import storage_warnings


def directory_usage(directory,seen=None):
    seen=seen if seen is not None else set();size=count=0
    if not directory.exists() or directory.is_symlink():return 0,0
    for root,dirs,files in os.walk(directory,followlinks=False):
        dirs[:]=[name for name in dirs if not (Path(root)/name).is_symlink()]
        for name in files:
            path=Path(root)/name
            try:
                if path.is_symlink() or not path.is_file():continue
                value=path.stat();key=(value.st_dev,value.st_ino)
                if key in seen:continue
                seen.add(key);size+=value.st_size;count+=1
            except OSError:continue
    return size,count


def project_usage(db,project,user):
    files={};removed_bytes=removed_count=missing=0
    for asset in db.query(models.Attachment).filter_by(project_id=project.id):
        if not docs.can_read_file(user,project,asset):continue
        if removal_record(asset,db):removed_bytes+=asset.file_size;removed_count+=1
        else:files[asset.stored_name]=asset.file_size
    definitions=db.query(models.ProjectDocumentDefinition).filter_by(project_id=project.id).all()
    documents=db.query(models.ProjectDocument).filter_by(project_id=project.id).all()
    allowed=set()
    for row in definitions:
        checker=getattr(docs,'can_read_definition',None)
        if row.blank_file_id and (checker(user,project,row) if checker else not row.confidential_default):allowed.add(row.blank_file_id)
    for row in documents:
        if row.blank_file_id and docs.can_read_document(user,project,row):allowed.add(row.blank_file_id)
    for blank in db.query(models.DocumentTemplateFile).filter(models.DocumentTemplateFile.id.in_(allowed)):
        if docs.can_read_blank(db,user,blank,project):files[blank.stored_name]=blank.file_size
    total=count=0
    for stored,size in files.items():
        path=config.UPLOAD_DIR/stored
        if Path(stored).name!=stored or path.is_symlink() or not path.is_file():missing+=1;continue
        total+=path.stat().st_size;count+=1
    temporary=0
    manageable=C_UPDATE in project_capabilities(user,project)
    for session in db.query(models.UploadSession).filter_by(project_id=project.id):
        if session.owner_id==user.id or manageable:temporary+=directory_usage(config.DATA_DIR/'.upload-sessions'/session.id)[0]
    return {'project_id':project.id,'project_name':project.name,'state':project.status,'bytes':total,'file_count':count,
        'removed_bytes':removed_bytes,'removed_file_count':removed_count,'temporary_bytes':temporary,'missing_file_count':missing,
        'can_cleanup':manageable and project.status!='archived' and not (project.legacy_lifecycle or {}).get('requires_repair'),
        'storage_warnings':storage_warnings(db,project,user)}


def global_usage(db,user):
    from app.services.scope import visible_projects
    seen=set();size,count=directory_usage(config.UPLOAD_DIR,seen)
    temporary=directory_usage(config.DATA_DIR/'.upload-sessions',seen)[0]+directory_usage(config.DATA_DIR/'.storage-trash',seen)[0]
    removed=db.query(models.FileRemovalRecord).all()
    return {'max_upload_size':config.MAX_UPLOAD_BYTES,'bytes':size,'file_count':count,'temporary_bytes':temporary,
        'removed_bytes':sum(row.file_size for row in removed),
        'projects':[project_usage(db,project,user) for project in visible_projects(db,user)],
        'time_basis':'文件大小按当前存在的原件统计；项目共享文件按引用计数，分项目数值不能简单相加。已清理字节仅保留元数据，不计作仍存在的原件。'}
