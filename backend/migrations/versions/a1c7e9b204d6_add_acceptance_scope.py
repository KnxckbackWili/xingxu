"""Track acceptance scope without fabricating legacy evidence.

Revision ID: a1c7e9b204d6
Revises: f7b3c8d2a901
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1c7e9b204d6'
down_revision = 'f7b3c8d2a901'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('acceptance_records', sa.Column('scope_fingerprint', sa.String(64), nullable=True))


def downgrade():
    op.drop_column('acceptance_records', 'scope_fingerprint')
