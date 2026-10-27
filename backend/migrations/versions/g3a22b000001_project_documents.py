"""T22: project-owned document rules, instances and immutable evidence versions."""
from alembic import op
import sqlalchemy as sa
from migrations.v3_project_documents import migrate_legacy_documents

revision = "g3a22b000001"
down_revision = "g3a14b000001"
branch_labels = None
depends_on = None


def rule_columns():
    return [sa.Column('stage_key', sa.String(8), nullable=False), sa.Column('code', sa.String(80), nullable=False),
        sa.Column('name', sa.String(300), nullable=False), sa.Column('template_no', sa.String(100)),
        sa.Column('required', sa.Boolean(), nullable=False), sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('platform', sa.String(20)), sa.Column('timing_type', sa.String(24), nullable=False),
        sa.Column('timing_event', sa.String(32)), sa.Column('timing_offset_hours', sa.Integer()),
        sa.Column('timing_weekday', sa.Integer()), sa.Column('trigger_type', sa.String(20)),
        sa.Column('blank_file_id', sa.String(36), sa.ForeignKey('document_template_files.id', ondelete='SET NULL')),
        sa.Column('sort_order', sa.Integer(), nullable=False), sa.Column('note', sa.Text()), sa.Column('source_metadata', sa.JSON())]


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('T22需要在线逐条对账旧资料与文件，不支持离线跳过')
    op.add_column('attachments', sa.Column('confidential', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('attachments', sa.Column('sha256', sa.String(64)))
    op.add_column('document_requirements', sa.Column('source_metadata', sa.JSON()))
    definitions = op.create_table('project_document_definitions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('requirement_id', sa.String(36), sa.ForeignKey('document_requirements.id', ondelete='SET NULL')),
        sa.Column('source_key', sa.String(160), nullable=False), *rule_columns(),
        sa.Column('confidential_default', sa.Boolean(), nullable=False),
        sa.Column('external_visible_default', sa.Boolean(), nullable=False),
        sa.Column('external_never_visible', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime()),
        sa.UniqueConstraint('project_id', 'source_key', name='uq_project_document_definition_source'))
    op.create_index('ix_project_document_definitions_project_id', 'project_document_definitions', ['project_id'])
    documents = op.create_table('project_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('definition_id', sa.String(36), sa.ForeignKey('project_document_definitions.id', ondelete='SET NULL')),
        sa.Column('requirement_id', sa.String(36), sa.ForeignKey('document_requirements.id', ondelete='SET NULL')),
        sa.Column('instance_key', sa.String(250), nullable=False), *rule_columns(),
        sa.Column('vehicle_unit_id', sa.String(36), sa.ForeignKey('vehicle_units.id', ondelete='SET NULL')),
        sa.Column('vehicle_label', sa.String(200)), sa.Column('period_key', sa.String(32)), sa.Column('trigger_ref', sa.String(100)),
        sa.Column('due_at', sa.DateTime()), sa.Column('due_is_estimated', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('waived_reason', sa.Text()),
        sa.Column('confidential', sa.Boolean(), nullable=False), sa.Column('external_visible', sa.Boolean(), nullable=False),
        sa.Column('external_never_visible', sa.Boolean(), nullable=False),
        sa.Column('submitted_at', sa.DateTime()), sa.Column('submitted_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('created_at', sa.DateTime()),
        sa.UniqueConstraint('project_id', 'instance_key', name='uq_project_document_instance'),
        sa.CheckConstraint("status IN ('pending','submitted','waived')", name='ck_project_document_status'))
    op.create_index('ix_project_documents_project_id', 'project_documents', ['project_id'])
    versions = op.create_table('document_versions', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_document_id', sa.String(36), sa.ForeignKey('project_documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('attachment_id', sa.String(36), sa.ForeignKey('attachments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('uploaded_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('uploaded_at', sa.DateTime()), sa.Column('note', sa.Text()), sa.Column('review_metadata', sa.JSON()))
    op.create_index('ix_document_versions_project_document_id', 'document_versions', ['project_document_id'])
    op.create_index('ix_document_versions_attachment_id', 'document_versions', ['attachment_id'])
    migrate_legacy_documents(op.get_bind(), definitions, documents, versions)


def downgrade():
    raise RuntimeError('资料版本和旧事实不可丢弃；回退请恢复升级前一致加密备份')
