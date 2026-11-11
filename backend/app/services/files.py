"""Uploaded files on disk: one opaque name per file under the project's folder."""
import hashlib
import mimetypes
import re
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB, UPLOAD_DIR

INLINE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_name(name: str) -> str:
    """The name shown and offered for download; never used as a path on disk."""
    name = _CONTROL.sub("", (name or "").replace("\\", "/").rsplit("/", 1)[-1]).strip().strip(".")
    return name[:200] or "未命名"


def mime_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def absolute(storage_path: str) -> Path:
    root = UPLOAD_DIR.resolve()
    path = (root / storage_path).resolve()
    if root not in path.parents:
        raise HTTPException(404, "文件不存在")
    return path


async def store(upload: UploadFile, project_id: str, file_id: str) -> tuple[str, int, str]:
    """Stream the upload to disk. Returns (storage path, size, sha256)."""
    relative = f"{project_id}/{file_id}"
    target = absolute(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    size, digest = 0, hashlib.sha256()
    try:
        with target.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if MAX_UPLOAD_BYTES and size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"文件超过大小上限（{MAX_UPLOAD_MB} MB）")
                digest.update(chunk)
                output.write(chunk)
        if not size:
            raise HTTPException(400, "文件是空的")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return relative, size, digest.hexdigest()


def discard(storage_path: str) -> None:
    try:
        absolute(storage_path).unlink(missing_ok=True)
    except (HTTPException, OSError):
        pass
