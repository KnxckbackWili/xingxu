"""T24: issue nature and immutable document trigger provenance."""
from alembic import op
import sqlalchemy as sa

revision='g3a24b000001'
down_revision='g3a28b000001'
branch_labels=None
depends_on=None


def upgrade():
    # Existing issue_type/extra and reporting times stay byte-for-byte intact.
    # A historical record is not a new incident or membership departure.
    op.add_column('issues',sa.Column('nature',sa.String(20),nullable=False,server_default='normal'))
    op.add_column('issues',sa.Column('source_metadata',sa.JSON(),nullable=True))
    op.create_table('document_trigger_events',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('trigger_type',sa.String(20),nullable=False),
        sa.Column('source_type',sa.String(30),nullable=False),
        sa.Column('source_id',sa.String(36),nullable=False),
        sa.Column('source_key',sa.String(160),nullable=False),
        sa.Column('occurred_at',sa.DateTime(),nullable=False),
        sa.Column('recorded_at',sa.DateTime(),nullable=False),
        sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('source_metadata',sa.JSON(),nullable=False),
        sa.UniqueConstraint('project_id','source_key',name='uq_document_trigger_source'))
    op.create_index('ix_document_trigger_events_project_id','document_trigger_events',['project_id'])
    op.create_table('issue_sla_receipts',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('issue_id',sa.String(36),sa.ForeignKey('issues.id',ondelete='CASCADE'),nullable=False),
        sa.Column('nature',sa.String(20),nullable=False),
        sa.Column('sla_hours',sa.Integer(),nullable=False),
        sa.Column('recipient_id',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('recipient_key',sa.String(36),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('issue_id','nature','sla_hours','recipient_key',name='uq_issue_sla_delivery'))
    op.create_index('ix_issue_sla_receipts_project_id','issue_sla_receipts',['project_id'])


def downgrade():
    raise RuntimeError('触发来源与SLA投递属于审计事实；回退请恢复升级前一致备份')
