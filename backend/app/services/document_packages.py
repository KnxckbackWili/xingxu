"""Selected document evidence only; stream source bytes into bounded ZIP storage."""
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from fastapi import HTTPException
from app.models import Attachment, DocumentVersion
from app.services import project_documents as docs
from app.time_utils import utcnow


def export_directory():
    # Deployment /tmp is a 256-MiB tmpfs. Spill large ZIPs to private DATA_DIR,
    # using unnamed TemporaryFile handles that disappear even after a crash.
    from app import config
    path=config.DATA_DIR/'.export-staging'
    if path.is_symlink():raise HTTPException(409,'导出暂存目录不可用')
    path.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(path,0o700)
    return path


def selected_package(db, project, user, document_ids):
    from app.services.import_export import _safe_zip_name
    documents = [docs.owned_document(db, project.id, identity) for identity in document_ids]
    selections = []
    assets = {}
    for document in documents:
        if not docs.can_read_document(user, project, document):
            raise HTTPException(403, '所选资料包含未授权查看的内容')
        version = db.query(DocumentVersion).filter_by(project_document_id=document.id).order_by(
            DocumentVersion.uploaded_at.desc().nullslast(), DocumentVersion.id.desc()).first()
        asset = db.get(Attachment, version.attachment_id) if version else None
        if asset is None or asset.project_id != project.id:
            raise HTTPException(409, f'资料「{document.code} {document.name}」没有可打包的提交文件')
        if not docs.can_read_file(user, project, asset):
            raise HTTPException(403, '所选资料包含未授权查看的文件')
        assets[asset.id] = asset
        selections.append({'document_id': document.id, 'code': document.code, 'name': document.name,
            'status': document.status, 'vehicle_label': document.vehicle_label, 'period_key': document.period_key,
            'version_id': version.id, 'attachment_id': asset.id, 'uploaded_at': docs.iso(version.uploaded_at)})
    package = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b',dir=export_directory())
    manifest_files = {}
    try:
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for identity, asset in assets.items():
                path = docs.validate_file(asset)
                safe_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
                name = f'files/{safe_id}/{_safe_zip_name(asset.filename or "附件")}'
                digest = hashlib.sha256()
                size = 0
                try:
                    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                    with os.fdopen(descriptor, 'rb') as source:
                        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                            raise HTTPException(409, '原件不是常规文件，打包已停止')
                        with archive.open(name, 'w', force_zip64=True) as target:
                            while chunk := source.read(1024 * 1024):
                                target.write(chunk); digest.update(chunk); size += len(chunk)
                except OSError:
                    raise HTTPException(409, '原件不可读取，打包已停止，请负责人核对') from None
                if size != asset.file_size or (asset.sha256 and digest.hexdigest() != asset.sha256):
                    raise HTTPException(409, '原件完整性核对失败，打包已停止')
                manifest_files[identity] = {'attachment_id': identity, 'filename': asset.filename,
                    'archive_path': name, 'size': size, 'sha256': digest.hexdigest()}
            archive.writestr('manifest.json', json.dumps({'type': 'xingxu-selected-documents', 'version': 1,
                'project_id': project.id, 'generated_at': docs.iso(utcnow()), 'selection': 'latest_version',
                'documents': selections, 'files': list(manifest_files.values())}, ensure_ascii=False, indent=2).encode())
        package.seek(0)
        docs.audit_access(db,project,user,documents=documents,files=list(assets.values()),action='confidential_dl')
        db.commit()
        return package
    except BaseException:
        package.close()
        raise


def chunks(package):
    try:
        while chunk := package.read(1024 * 1024):
            yield chunk
    finally:
        package.close()
