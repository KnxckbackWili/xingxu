"""Records without gates (3.8.0).

- Issues no longer have a handling time limit, so the reminder receipts go.
- Weekly plans have no draft/published split: every saved cell is the plan and
  everyone can see it. Cells that were still drafts simply become plan cells.
"""
from alembic import op

revision = "h0b0000000003"
down_revision = "h0b0000000002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('issue_sla_receipts', schema=None) as batch_op:
        batch_op.drop_index('ix_issue_sla_receipts_project_id')
    op.drop_table('issue_sla_receipts')
    with op.batch_alter_table('weekly_plan_cells', schema=None) as batch_op:
        batch_op.drop_column('published_by')
        batch_op.drop_column('published_at')
        batch_op.drop_column('published')


def downgrade():
    raise NotImplementedError("3.8.0 removes data that cannot be restored; restore the pre-upgrade encrypted backup instead")
