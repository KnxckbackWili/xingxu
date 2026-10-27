"""Internal AI API token management.

Token 格式：agv_ai_<secret>；服务端只保存 SHA-256 hash。
Token 绑定系统账号，MCP/内部 AI 调用时以该账号的项目可见性与能力鉴权。
"""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user
from app.models import AiApiToken, User
from app.services.change_log import log_change
from app.services.agent_auth import active_agent_scopes
from app.services.system_permissions import has_permission
from app.time_utils import utcnow

router = APIRouter(prefix="/ai/internal", tags=["AI 内部接口"])


def _parse_expiry(value: str) -> datetime:
    """把 ISO-8601 字符串解析为 naive UTC datetime（与库列 DateTime 一致）。

    ``AiApiToken.expires_at`` 是 DateTime 列，直接把字符串赋给 ORM 属性在
    PostgreSQL 上 flush 时报错、在 SQLite 上则会存成文本导致读回时
    ``.isoformat()`` 崩溃——统一在此解析，非法输入给 400 而不是 500。
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="expires_at 必须是 ISO-8601 时间字符串"
        ) from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


from app.services.agent_catalog import DEFAULT_SCOPES, SCOPE_OPTIONS


class AiTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    user_id: str
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES))
    expires_at: Optional[str] = None


class AiTokenUpdate(BaseModel):
    name: Optional[str] = None
    scopes: Optional[list[str]] = None
    expires_at: Optional[str] = None
    is_active: Optional[bool] = None


def _admin(user: User = Depends(get_current_user)) -> User:
    if not has_permission(
        user, "system.agent_tokens.manage", default=user.role == "admin"
    ):
        raise HTTPException(status_code=403, detail="没有外部工具凭据管理权限")
    return user


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_dict(token: AiApiToken, user_name: str = "") -> dict:
    return {
        "id": token.id,
        "name": token.name,
        "token_prefix": token.token_prefix,
        "user_id": token.user_id,
        "user_name": user_name,
        "scopes": active_agent_scopes(token.scopes),
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "is_active": token.is_active,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "created_at": token.created_at.isoformat() if token.created_at else None,
    }


@router.get("/tokens")
@route_permission('system.agent_tokens.manage')
def list_tokens(user: User = Depends(_admin), db: Session = Depends(get_db)):
    query = db.query(AiApiToken)
    if user.role != "admin":
        query = query.filter(AiApiToken.user_id == user.id)
    rows = query.order_by(AiApiToken.created_at.desc()).all()
    users = {
        u.id: u.display_name
        for u in db.query(User).filter(User.id.in_({t.user_id for t in rows})).all()
    }
    from app.services.ai_budget import budget_status
    return {
        "budget": budget_status(db),
        "items": [_token_dict(t, users.get(t.user_id, "")) for t in rows],
        "scopes": SCOPE_OPTIONS,
    }


@router.post("/tokens")
@route_permission('system.agent_tokens.manage')
def create_token(
    data: AiTokenCreate, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    if user.role != "admin" and data.user_id != user.id:
        raise HTTPException(403, "受委托成员只能为本人创建外部工具凭据")
    target = db.get(User, data.user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail="绑定账号不存在或已停用")
    from app.services.two_factor import required
    if required(target) and (not target.mfa_enabled or target.id != user.id):
        raise HTTPException(403, "需先由该账号完成二次验证，并通过本人会话创建外部凭据")
    scopes = list(dict.fromkeys(data.scopes or []))
    unknown = [s for s in scopes if s not in dict(SCOPE_OPTIONS)]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"不支持的 scope：{', '.join(unknown)}"
        )
    secret = "agv_ai_" + secrets.token_urlsafe(32)
    row = AiApiToken(
        name=data.name.strip(),
        token_hash=_hash_token(secret),
        token_prefix=secret[:12],
        auth_version=target.token_version or 0,
        user_id=data.user_id,
        scopes=scopes,
        expires_at=_parse_expiry(data.expires_at) if data.expires_at else None,
        is_active=True,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    log_change(
        db,
        None,
        "ai_api_token",
        row.id,
        "create",
        user.id,
        f"创建内部 AI Token「{row.name}」",
    )
    db.commit()
    db.refresh(row)
    return {**_token_dict(row, target.display_name), "token": secret}


@router.put("/tokens/{token_id}")
@route_permission('system.agent_tokens.manage')
def update_token(
    token_id: str,
    data: AiTokenUpdate,
    user: User = Depends(_admin),
    db: Session = Depends(get_db),
):
    row = db.get(AiApiToken, token_id)
    if row is None or (user.role != "admin" and row.user_id != user.id):
        raise HTTPException(status_code=404, detail="Token 不存在")
    if data.name is not None:
        row.name = data.name.strip() or row.name
    if data.scopes is not None:
        unknown = [s for s in data.scopes if s not in dict(SCOPE_OPTIONS)]
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"不支持的 scope：{', '.join(unknown)}"
            )
        row.scopes = list(dict.fromkeys(data.scopes))
    if data.expires_at is not None:
        row.expires_at = _parse_expiry(data.expires_at)
    if data.is_active is not None:
        row.is_active = data.is_active
    db.flush()
    log_change(
        db,
        None,
        "ai_api_token",
        row.id,
        "update",
        user.id,
        f"更新内部 AI Token「{row.name}」",
    )
    db.commit()
    db.refresh(row)
    bound = db.get(User, row.user_id)
    return _token_dict(row, bound.display_name if bound else "")


@router.delete("/tokens/{token_id}")
@route_permission('system.agent_tokens.manage')
def revoke_token(
    token_id: str, user: User = Depends(_admin), db: Session = Depends(get_db)
):
    row = db.get(AiApiToken, token_id)
    if row is None or (user.role != "admin" and row.user_id != user.id):
        raise HTTPException(status_code=404, detail="Token 不存在")
    row.is_active = False
    db.flush()
    log_change(
        db,
        None,
        "ai_api_token",
        row.id,
        "update",
        user.id,
        f"停用内部 AI Token「{row.name}」",
    )
    db.commit()
    return {"message": "Token 已停用"}
