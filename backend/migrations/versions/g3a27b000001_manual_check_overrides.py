"""T27: retain the exact ordinary checks explicitly overridden by a manager."""
from alembic import op
import sqlalchemy as sa
revision = 'g3a27b000001'
down_revision = 'g3a23b000001'
branch_labels = None
depends_on = None


def upgrade():
    # Old human completion facts stay unchanged. Never invent past override consent.
    op.add_column('tasks', sa.Column('manual_check_overrides', sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError('检查项覆盖事实不可丢弃；回退请恢复升级前一致备份')
