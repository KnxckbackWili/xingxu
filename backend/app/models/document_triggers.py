"""Immutable sources for triggered evidence and durable issue-SLA delivery."""
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, UniqueConstraint
from app.db import Base
from app.models import gen_uuid
from app.time_utils import utcnow


class DocumentTriggerEvent(Base):
    __tablename__ = 'document_trigger_events'
    __table_args__ = (UniqueConstraint('project_id','source_key',name='uq_document_trigger_source'),)
    id = Column(String(36),primary_key=True,default=gen_uuid)
    project_id = Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    trigger_type = Column(String(20),nullable=False)
    source_type = Column(String(30),nullable=False)
    source_id = Column(String(36),nullable=False)
    source_key = Column(String(160),nullable=False)
    occurred_at = Column(DateTime,nullable=False)
    recorded_at = Column(DateTime,nullable=False,default=utcnow)
    actor_id = Column(String(36),ForeignKey('users.id',ondelete='SET NULL'))
    source_metadata = Column(JSON,nullable=False,default=dict)
