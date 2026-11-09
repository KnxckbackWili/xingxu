"""Two kinds of account and no management/approval tables (3.7.0).

- Accounts are either a system administrator or an employee. Every other role becomes
  employee; read-only accounts are disabled so nobody gains write access silently,
  and an administrator re-enables them deliberately.
- Removed: per-account permission switches, project technical lead, dispatch readiness
  reviews and confirmation fields, external sharing and its document visibility flags,
  agent/AI tokens and usage ledger, the retired weekly-plan intent flag, assisted
  field records (whoever records an operation is the one who did it), the old module
  layer between stages and work, and the readiness checklist (only procurement stays).
"""
import sqlalchemy as sa
from alembic import op

revision = "h0b0000000002"
down_revision = "h0b0000000001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE users SET is_active = false WHERE role = 'readonly'")
    op.execute("UPDATE users SET role = 'employee' WHERE role <> 'admin'")

    with op.batch_alter_table('ai_usage_ledger', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_usage_ledger_month')
    op.drop_table('ai_usage_ledger')
    with op.batch_alter_table('project_readiness_reviews', schema=None) as batch_op:
        batch_op.drop_index('ix_project_readiness_reviews_project_id')
    op.drop_table('project_readiness_reviews')
    with op.batch_alter_table('external_access_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_external_access_logs_project_id')
        batch_op.drop_index('ix_external_access_logs_share_id')
    op.drop_table('external_access_logs')
    with op.batch_alter_table('ai_api_tokens', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_api_tokens_token_hash')
        batch_op.drop_index('ix_ai_api_tokens_user_id')
    op.drop_table('ai_api_tokens')
    with op.batch_alter_table('external_shares', schema=None) as batch_op:
        batch_op.drop_index('ix_external_shares_project_id')
    op.drop_table('external_shares')

    for table in ('document_requirements', 'project_document_definitions'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('external_visible_default')
            batch_op.drop_column('external_never_visible')
    with op.batch_alter_table('project_documents', schema=None) as batch_op:
        batch_op.drop_column('external_never_visible')
        batch_op.drop_column('external_visible')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        for column in ('schedule_version', 'prep_confirmed_at', 'prep_conclusion', 'prep_confirmed_by',
                       'readiness_state', 'technical_manager'):
            batch_op.drop_column(column)
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('permission_version')
        batch_op.drop_column('permission_overrides')
    with op.batch_alter_table('weekly_plan_cells', schema=None) as batch_op:
        batch_op.drop_column('intent_review_required')
    with op.batch_alter_table('field_operations', schema=None) as batch_op:
        batch_op.drop_column('assisted_user_id')

    # Work belongs directly to a stage; the old module layer and readiness checklist go.
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index('ix_tasks_module_id')
        batch_op.drop_column('module_id')
        batch_op.drop_column('scope_conditions')
    with op.batch_alter_table('modules', schema=None) as batch_op:
        batch_op.drop_index('ix_modules_project_id')
        batch_op.drop_index('ix_modules_source_module_id')
        batch_op.drop_index('ix_modules_template_id')
    op.drop_table('modules')
    op.drop_table('template_preparation_items')
    op.execute("DELETE FROM project_preparation_items WHERE category <> 'procurement'")
    with op.batch_alter_table('project_preparation_items', schema=None) as batch_op:
        for column in ('task_id', 'blocks_entry', 'affected_phase_id', 'affected_task_id', 'planned_date'):
            batch_op.drop_column(column)
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('prep_conditions')


def downgrade():
    raise NotImplementedError("3.7.0 removes data that cannot be restored; restore the pre-upgrade encrypted backup instead")
