"""One template per vehicle type: templates carry the vehicle type they are for (empty = general)."""
from alembic import op
import sqlalchemy as sa

revision = 'g3a92b000001'
down_revision = 'g3a91b000001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('templates', sa.Column('vehicle_type', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('templates', 'vehicle_type')
