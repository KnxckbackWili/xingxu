"""Project-owned requirement snapshots and evidence versions."""
from uuid import uuid4
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, JSON, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.db import Base
from app.time_utils import utcnow


def identifier():
    return str(uuid4())


class DocumentRuleFields:
    stage_key = Column(String(8), nullable=False)
    code = Column(String(80), nullable=False)
    name = Column(String(300), nullable=False)
    template_no = Column(String(100), default="")
    required = Column(Boolean, nullable=False, default=True)
    scope = Column(String(20), nullable=False, default="project")
    platform = Column(String(20), nullable=True)
    timing_type = Column(String(24), nullable=False, default="on_demand")
    timing_event = Column(String(32), nullable=True)
    timing_offset_hours = Column(Integer, nullable=True)
    timing_weekday = Column(Integer, nullable=True)
    trigger_type = Column(String(20), nullable=True)
    blank_file_id = Column(String(36), ForeignKey("document_template_files.id", ondelete="SET NULL"), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    note = Column(Text, default="")
    source_metadata = Column(JSON, nullable=True)
    owner_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ProjectDocumentDefinition(DocumentRuleFields, Base):
    """Snapshot copied once; periodic/trigger instances never read a mutable template."""
    __tablename__ = "project_document_definitions"
    id = Column(String(36), primary_key=True, default=identifier)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id = Column(String(36), ForeignKey("document_requirements.id", ondelete="SET NULL"), nullable=True)
    source_key = Column(String(160), nullable=False)
    confidential_default = Column(Boolean, nullable=False, default=False)
    confidential_user_ids = Column(JSON().with_variant(JSONB(), 'postgresql'), nullable=False, default=list, server_default="[]")
    access_version = Column(Integer, nullable=False, default=1, server_default="1")
    external_visible_default = Column(Boolean, nullable=False, default=False)
    external_never_visible = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("project_id", "source_key", name="uq_project_document_definition_source"),)


class ProjectDocument(DocumentRuleFields, Base):
    __tablename__ = "project_documents"
    id = Column(String(36), primary_key=True, default=identifier)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    definition_id = Column(String(36), ForeignKey("project_document_definitions.id", ondelete="SET NULL"), nullable=True)
    requirement_id = Column(String(36), ForeignKey("document_requirements.id", ondelete="SET NULL"), nullable=True)
    instance_key = Column(String(250), nullable=False)
    vehicle_unit_id = Column(String(36), ForeignKey("vehicle_units.id", ondelete="SET NULL"), nullable=True)
    vehicle_label = Column(String(200), default="")
    period_key = Column(String(32), nullable=True)
    trigger_ref = Column(String(100), nullable=True)
    due_at = Column(DateTime, nullable=True)
    due_is_estimated = Column(Boolean, nullable=False, default=False)
    due_basis = Column(JSON, nullable=True)
    triggered_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    waived_reason = Column(Text, default="")
    confidential = Column(Boolean, nullable=False, default=False)
    confidential_user_ids = Column(JSON().with_variant(JSONB(), 'postgresql'), nullable=False, default=list, server_default="[]")
    external_visible = Column(Boolean, nullable=False, default=False)
    external_never_visible = Column(Boolean, nullable=False, default=False)
    submitted_at = Column(DateTime, nullable=True)
    submitted_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint("project_id", "instance_key", name="uq_project_document_instance"),
        CheckConstraint("status IN ('pending','submitted','waived')", name="ck_project_document_status"),
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id = Column(String(36), primary_key=True, default=identifier)
    project_document_id = Column(String(36), ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    attachment_id = Column(String(36), ForeignKey("attachments.id", ondelete="RESTRICT"), nullable=False, index=True)
    uploaded_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)
    note = Column(Text, default="")
    review_metadata = Column(JSON, nullable=True)


class DocumentNoticeReceipt(Base):
    """Durable deduplication for one recipient and one deadline revision."""
    __tablename__ = "document_notice_receipts"
    id = Column(String(36), primary_key=True, default=identifier)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    project_document_id = Column(String(36), ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recipient_key = Column(String(36), nullable=False)
    kind = Column(String(24), nullable=False)
    due_at = Column(DateTime, nullable=False)
    due_is_estimated = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("project_document_id", "recipient_key", "kind", "due_at", "due_is_estimated", name="uq_document_notice_revision"),)


class ProjectReportReceipt(Base):
    """One scheduled weekly report per project and local ISO week."""
    __tablename__ = "project_report_receipts"
    id = Column(String(36), primary_key=True, default=identifier)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    period_key = Column(String(10), nullable=False)
    delivery_pending = Column(Boolean, nullable=False, default=False)
    recipient_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    delivered_at = Column(DateTime, default=utcnow)
    summary = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("project_id", "period_key", name="uq_project_weekly_report"),)
