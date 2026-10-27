"""Bounded upload readers shared by public file endpoints."""

from fastapi import HTTPException, UploadFile


async def read_upload_limited(file: UploadFile, limit: int, label: str = "文件") -> bytes:
    data = bytearray()
    while chunk := await file.read(min(1024 * 1024, limit + 1 - len(data))):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(status_code=413, detail=f"{label}超过大小限制（{limit // 1024 // 1024}MB）")
    if not data:
        raise HTTPException(status_code=400, detail=f"{label}为空")
    return bytes(data)
