"""Shared bearer authentication for MCP and HTTP agents; no browser-session fallback."""

import hashlib
from datetime import timedelta

from fastapi import HTTPException

from app.db import SessionLocal
from app.models import AiApiToken, User
from app.time_utils import utcnow


def active_agent_scopes(scopes: list[str] | None) -> list[str]:
    """Exclude retired capabilities from both token views and authentication."""
    from app.services.agent_catalog import ACTIVE_SCOPES
    return list(dict.fromkeys(scope for scope in scopes or [] if scope in ACTIVE_SCOPES))


class AgentScopes(list):
    def __init__(self, values, token_id):
        super().__init__(values)
        self.token_id = token_id


def enforce_agent_mfa(db, user, token_id):
    from app.services.two_factor import agent_allowed, required
    row = db.get(AiApiToken, token_id) if token_id else None
    if row is None:
        if token_id or required(user):
            raise HTTPException(401, '此账号须完成二次验证并重新创建本人Agent凭据')
        return
    if not row.is_active or (row.expires_at and row.expires_at <= utcnow()) or row.user_id != user.id or not agent_allowed(user, row):
        raise HTTPException(401, 'Agent凭据的二次验证或账号状态已失效，请重新创建')


def authenticate_agent(authorization: str) -> tuple[str, list[str]]:
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith("agv_ai_"):
        raise HTTPException(401, "缺少有效的 Agent Token")
    with SessionLocal() as db:
        row = (
            db.query(AiApiToken)
            .filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest())
            .first()
        )
        now = utcnow()
        if (
            row is None
            or not row.is_active
            or (row.expires_at and row.expires_at <= now)
        ):
            raise HTTPException(401, "Agent Token 无效或已过期")
        user = db.get(User, row.user_id)
        if user is None or not user.is_active:
            raise HTTPException(401, "Agent Token 绑定的系统账号不可用")
        enforce_agent_mfa(db, user, row.id)
        from app.services.system_permissions import has_permission

        if not has_permission(user, "system.agent.use", default=True):
            raise HTTPException(403, "外部工具访问权限已被系统管理员撤销")
        identity = user.id, AgentScopes(active_agent_scopes(row.scopes), row.id)
        # Polling agents should not acquire a SQLite write lock on every read.
        if row.last_used_at is None or now - row.last_used_at >= timedelta(minutes=5):
            row.last_used_at = now
            db.commit()
        return identity
