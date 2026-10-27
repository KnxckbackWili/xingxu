"""Hash-only external grants and append-only access evidence."""
from uuid import uuid4
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from app.db import Base
from app.time_utils import utcnow


class ExternalShare(Base):
    __tablename__ = 'external_shares'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    scopes = Column(JSON, nullable=False)
    document_ids = Column(JSON, nullable=False, default=list)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    version = Column(Integer, nullable=False, default=1)


class ExternalAccessLog(Base):
    __tablename__ = 'external_access_logs'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=True, index=True)
    share_id = Column(String(36), ForeignKey('external_shares.id', ondelete='CASCADE'), nullable=True, index=True)
    occurred_at = Column(DateTime, nullable=False, default=utcnow)
    ip = Column(String(64), nullable=False)
    action = Column(String(20), nullable=False)
    resource_id = Column(String(36), nullable=True)
    status_code = Column(Integer, nullable=False)
