"""T23: deadline provenance, responsible users and durable scheduler receipts."""
from alembic import op
import sqlalchemy as sa

revision = "g3a23b000001"
down_revision = "g3a85b000001"
branch_labels = None
depends_on = None


def upgrade():
    frozen=_g22_tables() if op.get_context().as_sql and op.get_context().dialect.name=='sqlite' else {}
    for table in ("project_document_definitions", "project_documents"):
        if op.get_context().dialect.name=='sqlite':
            # The migration environment disables FKs transactionally during batch
            # DDL and verifies them before commit. IDs and version rows stay intact.
            with op.batch_alter_table(table,copy_from=frozen.get(table)) as batch:
                batch.add_column(sa.Column('owner_id',sa.String(36),nullable=True))
                batch.create_foreign_key(f'fk_{table}_owner','users',['owner_id'],['id'],ondelete='SET NULL')
        else:
            op.add_column(table,sa.Column('owner_id',sa.String(36),
                sa.ForeignKey('users.id',ondelete='SET NULL',name=f'fk_{table}_owner'),nullable=True))
    op.add_column("project_documents", sa.Column("due_basis", sa.JSON(), nullable=True))
    op.add_column("project_documents", sa.Column("triggered_at", sa.DateTime(), nullable=True))
    op.create_table("document_notice_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_document_id", sa.String(36), sa.ForeignKey("project_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("recipient_key", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("due_is_estimated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.UniqueConstraint("project_document_id", "recipient_key", "kind", "due_at", "due_is_estimated", name="uq_document_notice_revision"))
    op.create_index("ix_document_notice_receipts_project_id", "document_notice_receipts", ["project_id"])
    op.create_table("project_report_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_key", sa.String(10), nullable=False),
        sa.Column("delivery_pending",sa.Boolean(),nullable=False),
        sa.Column("recipient_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("delivered_at", sa.DateTime()),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "period_key", name="uq_project_weekly_report"))
    op.create_index("ix_project_report_receipts_project_id", "project_report_receipts", ["project_id"])


def downgrade():
    raise RuntimeError("提醒、截止依据与周报是审计事实；回退请恢复升级前一致备份")


def _g22_tables():
    """Frozen source schema for SQLite offline batch SQL; never imports live ORM."""
    from migrations.versions.g3a22b000001_project_documents import rule_columns
    metadata=sa.MetaData()
    for name in ('users','projects','document_requirements','document_template_files','vehicle_units'):
        sa.Table(name,metadata,sa.Column('id',sa.String(36),primary_key=True))
    definitions=sa.Table('project_document_definitions',metadata,
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('requirement_id',sa.String(36),sa.ForeignKey('document_requirements.id',ondelete='SET NULL')),
        sa.Column('source_key',sa.String(160),nullable=False),*rule_columns(),
        sa.Column('confidential_default',sa.Boolean(),nullable=False),
        sa.Column('external_visible_default',sa.Boolean(),nullable=False),
        sa.Column('external_never_visible',sa.Boolean(),nullable=False),
        sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('created_at',sa.DateTime()),
        sa.UniqueConstraint('project_id','source_key',name='uq_project_document_definition_source'))
    sa.Index('ix_project_document_definitions_project_id',definitions.c.project_id)
    documents=sa.Table('project_documents',metadata,
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('definition_id',sa.String(36),sa.ForeignKey('project_document_definitions.id',ondelete='SET NULL')),
        sa.Column('requirement_id',sa.String(36),sa.ForeignKey('document_requirements.id',ondelete='SET NULL')),
        sa.Column('instance_key',sa.String(250),nullable=False),*rule_columns(),
        sa.Column('vehicle_unit_id',sa.String(36),sa.ForeignKey('vehicle_units.id',ondelete='SET NULL')),
        sa.Column('vehicle_label',sa.String(200)),sa.Column('period_key',sa.String(32)),sa.Column('trigger_ref',sa.String(100)),
        sa.Column('due_at',sa.DateTime()),sa.Column('due_is_estimated',sa.Boolean(),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),sa.Column('waived_reason',sa.Text()),
        sa.Column('confidential',sa.Boolean(),nullable=False),sa.Column('external_visible',sa.Boolean(),nullable=False),
        sa.Column('external_never_visible',sa.Boolean(),nullable=False),sa.Column('submitted_at',sa.DateTime()),
        sa.Column('submitted_by',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime()),
        sa.UniqueConstraint('project_id','instance_key',name='uq_project_document_instance'),
        sa.CheckConstraint("status IN ('pending','submitted','waived')",name='ck_project_document_status'))
    sa.Index('ix_project_documents_project_id',documents.c.project_id)
    return {row.name:row for row in (definitions,documents)}
