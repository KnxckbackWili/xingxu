"""T14: encrypted TOTP enrollment, one-use challenges and recovery codes."""
from alembic import op
import sqlalchemy as sa

revision = 'g3a14b000001'
down_revision = 'g3a21b000001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('mfa_secret_encrypted', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('mfa_last_step', sa.BigInteger(), nullable=False, server_default='-1'))
    op.add_column('ai_api_tokens', sa.Column('auth_version', sa.Integer(), nullable=True))
    op.create_table('mfa_challenges',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('token_version', sa.Integer(), nullable=False),
        sa.Column('login_key', sa.String(256), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('pending_secret_encrypted', sa.Text(), nullable=True))
    op.create_table('mfa_recovery_codes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('code_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True))
    op.create_index('ix_mfa_recovery_codes_user_id', 'mfa_recovery_codes', ['user_id'])


def downgrade():
    raise RuntimeError('二次验证状态和恢复码不能丢弃；请恢复升级前一致加密备份')
