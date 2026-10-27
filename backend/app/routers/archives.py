"""T008: 项目物理清理归档（project_archives）只读查询路由。

物理清理前的不可变快照 + 审计链 + 校验哈希在此按原 project_id 可查。
仅 admin/director 可读；本路由不提供任何写端点，归档记录不可被普通业务接口
修改或删除。
"""

import hashlib
import json
from pathlib import Path
import re

from fastapi.responses import FileResponse
from app.services.system_permissions import route_permission
from app.config import UPLOAD_DIR

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User, ProjectArchive

router = APIRouter(tags=["归档"])


def _require_admin_or_director(user: User = Depends(get_current_user)):
    from app.services.system_permissions import has_permission
    if user.role=='external' or not has_permission(user, "system.archives.read", default=user.role in ("admin", "director")):
        raise HTTPException(status_code=403, detail="只有管理员或总监可查看项目归档")
    return user


def _archive_dict(archive: ProjectArchive) -> dict:
    return {
        "legacy_read_only": True,
        "id": archive.id,
        "project_id": archive.project_id,
        "project_name": archive.project_name,
        "actor_ids": archive.actor_ids or [],
        "checksum": archive.checksum,
        "purged_at": archive.purged_at.isoformat() if archive.purged_at else None,
        "created_at": archive.created_at.isoformat() if archive.created_at else None,
        "snapshot": archive.snapshot,
        "change_logs": archive.change_logs or [],
    }


@router.get("/archives/projects")
@route_permission('system.archives.read')
def list_project_archives(
    _: User = Depends(_require_admin_or_director),
    db: Session = Depends(get_db),
):
    """全部项目归档列表（含原始 project_id / 项目名 / 哈希 / 清理时间）。"""
    items = db.query(ProjectArchive).order_by(ProjectArchive.purged_at.desc()).all()
    return [
        {
            "legacy_read_only": True,
            "id": a.id,
            "project_id": a.project_id,
            "project_name": a.project_name,
            "actor_ids": a.actor_ids or [],
            "checksum": a.checksum,
            "purged_at": a.purged_at.isoformat() if a.purged_at else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in items
    ]


@router.get("/archives/projects/{project_id}")
@route_permission('system.archives.read')
def get_project_archive(
    project_id: str,
    response:Response,
    user: User = Depends(_require_admin_or_director),
    db: Session = Depends(get_db),
):
    """按原 project_id 查询完整归档：项目快照 + 全部 change_logs + 操作者 + 时间 + 校验哈希。"""
    archive = db.query(ProjectArchive).filter(
        ProjectArchive.project_id == project_id,
    ).order_by(ProjectArchive.purged_at.desc()).first()
    if archive is None:
        raise HTTPException(status_code=404, detail="未找到该项目归档记录")
    from app.services.retained_document_access import authorize_archive_content
    if authorize_archive_content(archive,user):
        from app.services.change_log import log_change
        log_change(db,None,'project_archive',archive.id,'confidential_view',user.id,'读取获授权的旧归档保密原文')
        db.commit()
    response.headers['Cache-Control']='private, no-store'
    return _archive_dict(archive)


@router.get("/archives/projects/{project_id}/verify")
@route_permission('system.archives.read')
def verify_project_archive(
    project_id: str,
    _: User = Depends(_require_admin_or_director),
    db: Session = Depends(get_db),
):
    """重算校验哈希并与归档时记录比对，验证归档不可篡改。"""
    archive = db.query(ProjectArchive).filter(
        ProjectArchive.project_id == project_id,
    ).order_by(ProjectArchive.purged_at.desc()).first()
    if archive is None:
        raise HTTPException(status_code=404, detail="未找到该项目归档记录")
    recomputed = _archive_checksum(archive)
    return {
        "project_id": archive.project_id,
        "stored_checksum": archive.checksum,
        "recomputed_checksum": recomputed,
        "match": recomputed == archive.checksum,
    }


def _archive_checksum(archive: ProjectArchive) -> str:
    content = {
        "project": {"id": archive.project_id, "name": archive.project_name},
        "snapshot": archive.snapshot,
        "change_logs": archive.change_logs or [],
        "purged_at": archive.purged_at.isoformat() if archive.purged_at else None,
    }
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@router.get("/archives/projects/{project_id}/files/{stored_name}")
@route_permission('system.archives.read')
def download_retained_file(
    project_id: str, stored_name: str,
    user: User = Depends(_require_admin_or_director), db: Session = Depends(get_db),
):
    """Download only verified file evidence owned by this immutable archive."""
    archive = db.query(ProjectArchive).filter_by(project_id=project_id).order_by(ProjectArchive.purged_at.desc()).first()
    if archive is None:
        raise HTTPException(status_code=404, detail="未找到该项目归档记录")
    if _archive_checksum(archive) != archive.checksum:
        raise HTTPException(status_code=409, detail="归档校验失败，不能下载未验证的文件")
    manifest = (archive.snapshot or {}).get("binary_files", {}).get("manifest", [])
    item = next((row for row in manifest if isinstance(row, dict) and row.get("stored_name") == stored_name), None)
    if item is None:
        raise HTTPException(status_code=404, detail="归档未保留该文件记录，旧归档无法补回缺失证据")
    from app.services.retained_document_access import authorize_archive_content
    authorize_archive_content(archive,user,stored_name=stored_name)
    path = UPLOAD_DIR / stored_name
    if (Path(stored_name).name != stored_name or "\\" in stored_name
            or UPLOAD_DIR.resolve() not in path.resolve().parents):
        raise HTTPException(status_code=400, detail="归档文件路径无效")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="归档文件已丢失，请从系统完整备份恢复")
    expected = item.get("sha256", "")
    if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise HTTPException(status_code=409, detail="归档未保留可验证的文件哈希，请核对系统完整备份")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise HTTPException(status_code=409, detail="归档文件校验失败，文件可能已损坏或改变")
    filename = str(item.get("filename") or stored_name).replace("\\", "/").split("/")[-1]
    filename = re.sub(r"[\x00-\x1f\x7f]", "_", filename)[:200] or stored_name
    from app.services.change_log import log_change
    log_change(db,None,'project_archive',archive.id,'confidential_dl',user.id,'读取旧归档中权限及完整性已核对的文件')
    db.commit()
    return FileResponse(path, filename=filename, media_type="application/octet-stream",headers={'Cache-Control':'private, no-store'})
