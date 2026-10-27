"""T53 hash-only scoped external shares and request/file access evidence."""
from alembic import op
import sqlalchemy as sa

revision='g3a53b000001'
down_revision='g3a25b000001'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('external_shares',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('token_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('scopes',sa.JSON(),nullable=False),sa.Column('document_ids',sa.JSON(),nullable=False),
        sa.Column('expires_at',sa.DateTime(),nullable=False),sa.Column('revoked_at',sa.DateTime()),
        sa.Column('created_by',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('created_at',sa.DateTime(),nullable=False),sa.Column('version',sa.Integer(),nullable=False))
    op.create_index('ix_external_shares_project_id','external_shares',['project_id'])
    op.create_table('external_access_logs',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE')),
        sa.Column('share_id',sa.String(36),sa.ForeignKey('external_shares.id',ondelete='CASCADE')),
        sa.Column('occurred_at',sa.DateTime(),nullable=False),sa.Column('ip',sa.String(64),nullable=False),
        sa.Column('action',sa.String(20),nullable=False),sa.Column('resource_id',sa.String(36)),
        sa.Column('status_code',sa.Integer(),nullable=False))
    op.create_index('ix_external_access_logs_project_id','external_access_logs',['project_id'])
    op.create_index('ix_external_access_logs_share_id','external_access_logs',['share_id'])


def downgrade():
    raise RuntimeError('外部授权与访问事实不能丢弃；回退请恢复升级前一致加密备份')
