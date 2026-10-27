"""乐观锁：并发写保护。

客户端在更新请求里带上读取到的 version；服务端做原子 CAS（compare-and-swap）
校验并自增，不匹配则 409。version 缺省（旧前端）时跳过校验但仍自增——向后兼容。
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session, object_session


def require_client_version(client_version: Optional[int]) -> int:
    """Client-facing edits must carry the version they read; never a blind overwrite."""
    if client_version is None:
        raise HTTPException(status_code=428, detail="缺少版本号：请刷新后再保存，避免覆盖他人的修改")
    return client_version


def bump_version(entity, client_version: Optional[int], db: Optional[Session] = None) -> None:
    """原子校验客户端版本号并自增；并发冲突抛 409。

    用一条 ``UPDATE ... WHERE version = :expected`` 完成比较并自增（rowcount=1 成功，
    0 表示期间已被他人修改 → 409），比"先读内存版本号再自增"在并发双写下更可靠。
    调用点应在本事务的字段修改与 commit 之前执行。无 Session（临时对象/单测直调）时
    退回内存自增，保持向后兼容。
    """
    if db is None:
        db = object_session(entity)
    expected = entity.version or 0
    new_version = expected + 1
    if client_version is not None:
        try:
            if int(client_version) != expected:
                raise HTTPException(status_code=409, detail="数据已被他人修改，请刷新后重试")
        except (TypeError, ValueError):
            raise HTTPException(status_code=409, detail="版本号无效") from None
    if db is not None:
        # WHERE version = expected：若 rowcount 为 0，说明校验后到执行前已被他人提交，
        # 内存比对无法发现这种竞态——数据库原子地拒绝本次写入。
        from sqlalchemy import or_
        row_cond = type(entity).id == entity.id
        if expected == 0:
            # 存量行可能在补列前被 raw insert 写入 NULL version，等价视为 0。
            row_cond = row_cond & or_(type(entity).version == 0, type(entity).version.is_(None))
        else:
            row_cond = row_cond & (type(entity).version == expected)
        result = db.execute(
            update(type(entity)).where(row_cond).values(version=new_version)
        )
        if result.rowcount != 1:
            raise HTTPException(status_code=409, detail="数据已被他人修改，请刷新后重试")
    entity.version = new_version
