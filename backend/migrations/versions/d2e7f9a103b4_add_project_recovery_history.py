"""Add recoverable deletion cycles and own metadata edit history.

Revision ID: d2e7f9a103b4
Revises: b6d4e8f103a2
Whole new tables preserve all existing Project, User and execution columns.
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e7f9a103b4"
down_revision = "b6d4e8f103a2"
branch_labels = None
depends_on = None


def upgrade():
    existing = set() if op.get_context().as_sql else set(sa.inspect(op.get_bind()).get_table_names())
    # init_db registers both models before create_all, so a fresh install may
    # already have these tables when Alembic advances its single head.
    if "project_deletion_records" not in existing:
        op.create_table("project_deletion_records",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("deleted_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=False),
            sa.Column("status_before_delete", sa.String(20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("backup_name", sa.String(100), nullable=False),
            sa.Column("backup_sha256", sa.String(64), nullable=False),
            sa.Column("backup_bytes", sa.Integer(), nullable=False),
            sa.Column("protected_from_purge", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("restored_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("restored_at", sa.DateTime(), nullable=True))
        op.create_index("ix_project_deletion_records_project_id", "project_deletion_records", ["project_id"])
        op.create_index("ix_project_deletion_records_deleted_at", "project_deletion_records", ["deleted_at"])
    if "project_edit_history" not in existing:
        op.create_table("project_edit_history",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("chain_id", sa.String(36), nullable=False),
            sa.Column("save_version", sa.Integer(), nullable=False),
            sa.Column("guard_version", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(20), nullable=False, server_default="applied"),
            sa.Column("before_data", sa.JSON(), nullable=False),
            sa.Column("after_data", sa.JSON(), nullable=False),
            sa.Column("blocked_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_action_at", sa.DateTime(), nullable=True),
            sa.Column("last_action_version", sa.Integer(), nullable=True),
            sa.UniqueConstraint("project_id", "save_version", name="uq_project_edit_save_version"))
        for column in ("project_id", "actor_id", "chain_id"):
            op.create_index("ix_project_edit_history_" + column, "project_edit_history", [column])


def downgrade():
    existing = {"project_edit_history", "project_deletion_records"} if op.get_context().as_sql else set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("project_edit_history", "project_deletion_records"):
        if table in existing:
            op.drop_table(table)
