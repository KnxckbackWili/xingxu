"""Add inheritable user system action policies and a CAS version.

Revision ID: b6d4e8f103a2
Revises: a1c7e9b204d6
"""
from alembic import op
import sqlalchemy as sa

revision = "b6d4e8f103a2"
down_revision = "a1c7e9b204d6"
branch_labels = None
depends_on = None


def upgrade():
    # create_all runs before Alembic on fresh installs; don't add an existing
    # column twice. NULL policy on an existing account means inheritance.
    columns = set() if op.get_context().as_sql else {
        row["name"] for row in sa.inspect(op.get_bind()).get_columns("users")
    }
    if "permission_overrides" not in columns:
        op.add_column("users", sa.Column("permission_overrides", sa.JSON(), nullable=True))
    if "permission_version" not in columns:
        op.add_column("users", sa.Column("permission_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    columns = {"permission_version", "permission_overrides"} if op.get_context().as_sql else {
        row["name"] for row in sa.inspect(op.get_bind()).get_columns("users")
    }
    if "permission_version" in columns:
        op.drop_column("users", "permission_version")
    if "permission_overrides" in columns:
        op.drop_column("users", "permission_overrides")
