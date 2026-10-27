"""Add bounded per-member project operation grants.

Revision ID: f7b3c8d2a901
Revises: e5a2f7c9d104
"""
from alembic import op
import sqlalchemy as sa

revision = "f7b3c8d2a901"
down_revision = "e5a2f7c9d104"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("member_permissions", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("projects", "member_permissions")
