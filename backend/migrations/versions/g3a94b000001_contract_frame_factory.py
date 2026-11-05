"""Fields the company forms need, on the records they belong to.

项目合同号 (projects.contract_no) for the AGV lifecycle table; 门架号 and 出厂日期 of each real
vehicle (vehicle_units.frame_no / factory_date, read from the frame stamp and the nameplate) for the
product quality feedback form. Existing rows get empty values; nothing is guessed.
"""
from alembic import op
import sqlalchemy as sa

revision = 'g3a94b000001'
down_revision = 'g3a93b000001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('projects', sa.Column('contract_no', sa.String(100), nullable=True))
    op.add_column('vehicle_units', sa.Column('frame_no', sa.String(100), nullable=True))
    op.add_column('vehicle_units', sa.Column('factory_date', sa.Date, nullable=True))


def downgrade():
    op.drop_column('vehicle_units', 'factory_date')
    op.drop_column('vehicle_units', 'frame_no')
    op.drop_column('projects', 'contract_no')
