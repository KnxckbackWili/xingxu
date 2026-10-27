"""T33 append-only actual operator, completion date and correction evidence."""
from alembic import op
import sqlalchemy as sa
revision='g3a33b000001'
down_revision='g3a40b000001'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('field_operations',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('kind',sa.String(16),nullable=False),sa.Column('target_id',sa.String(36),nullable=False),
        sa.Column('step_key',sa.String(80),nullable=False),sa.Column('weekly_cell_id',sa.String(36)),
        sa.Column('target_label',sa.String(400),nullable=False),
        sa.Column('actor_id',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('assisted_user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('completion_date',sa.Date(),nullable=False),sa.Column('recorded_at',sa.DateTime(),nullable=False),
        sa.Column('is_done',sa.Boolean(),nullable=False),sa.Column('note',sa.Text(),nullable=False),
        sa.Column('action',sa.String(16),nullable=False),sa.Column('replaces_id',sa.String(36)),
        sa.Column('root_id',sa.String(36)),sa.Column('restores_id',sa.String(36)),sa.Column('reason',sa.Text(),nullable=False),
        sa.Column('before_state',sa.JSON(),nullable=False),sa.Column('after_version',sa.Integer(),nullable=False),
        sa.Column('sequence',sa.Integer(),nullable=False),
        sa.Column('client_uuid',sa.String(64),nullable=False),sa.Column('payload_hash',sa.String(64),nullable=False),
        sa.UniqueConstraint('project_id','actor_id','client_uuid',name='uq_field_operation_actor_uuid'),
        sa.UniqueConstraint('project_id','sequence',name='uq_field_operation_sequence'))
    op.create_index('ix_field_operations_project_id','field_operations',['project_id'])
    op.create_index('ix_field_operations_actor_id','field_operations',['actor_id'])


def downgrade():
    raise RuntimeError('实际操作与修订证据不能丢弃；请恢复升级前一致加密备份')
