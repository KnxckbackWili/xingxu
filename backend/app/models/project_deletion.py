"""Recoverable project deletion metadata; live business rows keep their identity."""
from uuid import uuid4
from sqlalchemy import Boolean, BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from app.db import Base


class ProjectDeletionRecord(Base):
    __tablename__ = "project_deletion_records"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    deleted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    deleted_at = Column(DateTime, nullable=False, index=True)
    status_before_delete = Column(String(20), nullable=False)
    reason = Column(Text, nullable=False, default="")
    snapshot = Column(JSON, nullable=False)
    backup_name = Column(String(100), nullable=False)
    backup_sha256 = Column(String(64), nullable=False)
    backup_bytes = Column(BigInteger().with_variant(Integer, 'sqlite'), nullable=False)
    protected_from_purge = Column(Boolean, nullable=False, default=True)
    restored_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    restored_at = Column(DateTime, nullable=True)


class ProjectPermanentBackup(Base):
    """Ciphertext receipt survives deletion; project_id deliberately has no FK."""
    __tablename__ = 'project_permanent_backups'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    project_name = Column(String(200), nullable=False)
    deletion_id = Column(String(36), nullable=False)
    project_version = Column(Integer, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    backup_name = Column(String(100), nullable=False)
    backup_sha256 = Column(String(64), nullable=False)
    backup_bytes = Column(BigInteger().with_variant(Integer, 'sqlite'), nullable=False)
    prepared_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    prepared_at = Column(DateTime, nullable=False)
    purged_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    purged_at = Column(DateTime, nullable=True)
