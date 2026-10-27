"""Explicitly authorized encrypted backup and staged recovery endpoints."""
import shutil
import tempfile
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.config import DATA_DIR, DATABASE_URL, MAX_BACKUP_UPLOAD_SIZE
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services import backup_crypto as codec
from app.services.change_log import log_change
from app.services.system_backup import BACKUP_DIR, PENDING_RESTORE, create_backup, validate_archive
from app.services.system_permissions import has_permission, route_permission

router = APIRouter(prefix="/system", tags=["系统管理"])


def backup_permission(capability: str, *, real_admin=False):
    def checker(actor: User = Depends(get_current_user)):
        if (real_admin and actor.role != "admin") or not has_permission(actor, capability):
            raise HTTPException(status_code=403, detail="没有权限执行此备份操作")
        return actor
    checker.required_permissions = (capability,)
    checker.capability = capability
    return checker


class BackupCreate(BaseModel):
    label: str = Field(default="manual", pattern="^[a-zA-Z0-9_-]{1,30}$")


class BackupEncryption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passphrase: SecretStr


def _audit_id(filename: str) -> str:
    # The shared change_log entity_id is VARCHAR(36) on PostgreSQL. Preserve
    # the complete filename in JSON rather than overflowing that common key.
    return uuid5(NAMESPACE_URL, "xingxu-system-backup:" + filename).hex


def _item(path: Path) -> dict:
    return {"filename": path.name, "size": path.stat().st_size,
            "created_at": path.stat().st_mtime, "encrypted": codec.is_encrypted(path)}


@router.get("/backups")
@route_permission("system.backups.read")
def list_backups(_: User = Depends(backup_permission("system.backups.read"))):
    items = sorted([path for pattern in ("agvpm-*.tar.gz", "agvpm-*.tar.gz.agvenc")
                    for path in BACKUP_DIR.glob(pattern) if not path.is_symlink() and path.is_file()],
                   key=lambda item: item.stat().st_mtime, reverse=True)
    return {"items": [_item(path) for path in items if not path.is_symlink() and path.is_file()],
            "restore_pending": PENDING_RESTORE.exists(), "encryption": codec.passphrase_status(DATA_DIR),
            "database": "postgresql" if DATABASE_URL.startswith("postgresql") else "sqlite",
            "web_restore_supported": not DATABASE_URL.startswith("postgresql")}


@router.put("/backup-encryption")
@route_permission("system.backups.configure")
def configure_encryption(body: BackupEncryption,
                         actor: User = Depends(backup_permission("system.backups.configure", real_admin=True)),
                         db: Session = Depends(get_db)):
    previous = codec.passphrase_status(DATA_DIR)
    try:
        with codec.passphrase_update(DATA_DIR, body.passphrase.get_secret_value()):
            log_change(db, None, "system_backup", "encryption", "configure", actor.id,
                       "设置备份加密口令；仅影响之后生成的备份", old_value={"configured": previous["configured"]},
                       new_value={"configured": True})
            db.commit()
    except (codec.BackupError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error) if isinstance(error, codec.BackupError) else "备份口令暂时无法保存") from None
    return codec.passphrase_status(DATA_DIR)


@router.post("/backups")
@route_permission("system.backups.create")
def create_system_backup(body: BackupCreate, actor: User = Depends(backup_permission("system.backups.create")),
                         db: Session = Depends(get_db)):
    try:
        path = create_backup(body.label)
    except codec.BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    try:
        log_change(db, None, "system_backup", _audit_id(path.name), "create", actor.id, "创建加密系统备份",
                   new_value={"filename": path.name, "encrypted": True})
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return _item(path)


def _backup_path(filename: str) -> Path:
    if not filename.startswith("agvpm-") or Path(filename).name != filename or not filename.endswith((".tar.gz", ".agvenc")):
        raise HTTPException(status_code=400, detail="备份文件名无效")
    path = BACKUP_DIR / filename
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="备份不存在")
    return path


@router.get("/backups/{filename}")
@route_permission("system.backups.download")
def download_backup(filename: str, actor: User = Depends(backup_permission("system.backups.download")),
                    db: Session = Depends(get_db)):
    path = _backup_path(filename)
    if codec.is_encrypted(path):
        return FileResponse(path, filename=filename, media_type="application/octet-stream")
    temporary = BACKUP_DIR / f".download-{uuid4().hex}.agvenc"
    try:
        codec.encrypt_file(path, temporary, codec.get_passphrase(DATA_DIR))
        log_change(db, None, "system_backup", _audit_id(filename), "export", actor.id, "加密下载历史明文系统备份；原文件保留",
                   new_value={"filename": filename, "encrypted": True})
        db.commit()
    except codec.BackupError as error:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from None
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return FileResponse(temporary, filename=filename + ".agvenc", media_type="application/octet-stream",
                        background=BackgroundTask(temporary.unlink, missing_ok=True))


@router.delete("/backups/{filename}")
@route_permission("system.backups.delete")
def delete_backup(filename: str, actor: User = Depends(backup_permission("system.backups.delete")),
                  db: Session = Depends(get_db)):
    path = _backup_path(filename)
    held = path.with_name(".delete-" + uuid4().hex)
    path.replace(held)
    try:
        log_change(db, None, "system_backup", _audit_id(filename), "delete", actor.id, "删除系统备份",
                   old_value={"filename": filename})
        db.commit()
    except Exception:
        held.replace(path)
        raise
    held.unlink()
    return {"message": "备份已删除"}


@router.post("/restore")
@route_permission("system.backups.restore")
async def stage_restore(file: UploadFile = File(...), confirm: str = "",
                        passphrase: SecretStr = Form(default=SecretStr("")),
                        actor: User = Depends(backup_permission("system.backups.restore")),
                        db: Session = Depends(get_db)):
    if DATABASE_URL.startswith("postgresql"):
        raise HTTPException(status_code=400, detail="PostgreSQL 部署不支持网页恢复，请使用 docker/scripts/restore.sh 恢复备份")
    if confirm != "RESTORE":
        raise HTTPException(status_code=400, detail="恢复确认口令不正确")
    try:
        # The current installation must be able to protect its pre-restore snapshot.
        codec.get_passphrase(DATA_DIR)
    except codec.BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    upload = tempfile.NamedTemporaryFile(prefix=".restore-", suffix=".upload", dir=PENDING_RESTORE.parent, delete=False)
    temporary = Path(upload.name)
    pending = None
    size = 0
    try:
        with upload as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BACKUP_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="恢复包超过系统大小限制")
                target.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="恢复包为空")
        try:
            with codec.plain_archive(temporary, passphrase.get_secret_value(), directory=PENDING_RESTORE.parent) as plaintext:
                manifest = validate_archive(plaintext)
                if manifest["database"] != "sqlite":
                    raise codec.BackupError("当前 SQLite 部署只能恢复 SQLite 备份；PostgreSQL 备份请使用对应的宿主恢复工具")
                # Keep the private, already-authenticated internal staging protocol:
                # no passphrase has to be retained or sent through a container restart.
                with tempfile.NamedTemporaryFile(prefix=".restore-verified-", dir=PENDING_RESTORE.parent, delete=False) as output:
                    pending = Path(output.name)
                    with plaintext.open("rb") as source:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    output.flush()
                    import os
                    os.fsync(output.fileno())
            if PENDING_RESTORE.is_symlink():
                raise codec.BackupError("待恢复路径不安全")
            log_change(db, None, "system_backup", _audit_id(file.filename or "upload"), "restore", actor.id,
                       "验证备份口令与认证标签并准备系统恢复", new_value={"database": manifest["database"], "filename": file.filename or "upload"})
            db.commit()
            pending.replace(PENDING_RESTORE)
        except codec.BackupError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
    finally:
        temporary.unlink(missing_ok=True)
        if pending is not None:
            pending.unlink(missing_ok=True)
    return {"message": "备份口令及完整性已验证，请重启 Docker 容器应用恢复", "manifest": manifest}
