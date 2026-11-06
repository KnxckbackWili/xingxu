"""Starting point of the schema (3.6.0): every table as the models define it.

Earlier databases are not upgraded from here; the app moves them aside and starts empty
(app/db.py). Later schema changes are new revisions on top of this one.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "h0b0000000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ai_usage_ledger',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('month', sa.String(length=7), nullable=False),
    sa.Column('requests', sa.Integer(), nullable=True),
    sa.Column('tokens', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('month', name='uq_ai_usage_month')
    )
    op.create_index(op.f('ix_ai_usage_ledger_month'), 'ai_usage_ledger', ['month'], unique=False)
    op.create_table('holiday_calendars',
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('holidays', sa.JSON(), nullable=False),
    sa.Column('workdays', sa.JSON(), nullable=False),
    sa.Column('source_name', sa.String(length=300), nullable=False),
    sa.Column('source_url', sa.String(length=1000), nullable=False),
    sa.Column('published_on', sa.Date(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('year >= 1900 AND year <= 2200', name='ck_holiday_calendar_year'),
    sa.PrimaryKeyConstraint('year')
    )
    op.create_table('login_failure_buckets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('bucket', sa.Integer(), nullable=False),
    sa.Column('window', sa.Integer(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key', 'bucket', 'window', name='uq_login_failure_key_bucket_window')
    )
    op.create_index(op.f('ix_login_failure_buckets_key'), 'login_failure_buckets', ['key'], unique=False)
    op.create_table('notification_channel_configs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('channel', sa.String(length=30), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('webhook_url_encrypted', sa.Text(), nullable=True),
    sa.Column('secret_encrypted', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('last_test_at', sa.DateTime(), nullable=True),
    sa.Column('last_test_success', sa.Boolean(), nullable=True),
    sa.Column('last_test_detail', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_channel_configs_channel'), 'notification_channel_configs', ['channel'], unique=True)
    op.create_table('notification_outbox',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('notification_id', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('ntype', sa.String(length=30), nullable=True),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=True),
    sa.Column('max_attempts', sa.Integer(), nullable=True),
    sa.Column('next_retry_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_outbox_idempotency_key'), 'notification_outbox', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_notification_outbox_next_retry_at'), 'notification_outbox', ['next_retry_at'], unique=False)
    op.create_index(op.f('ix_notification_outbox_status'), 'notification_outbox', ['status'], unique=False)
    op.create_table('offline_op_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('op_type', sa.String(length=20), nullable=False),
    sa.Column('client_uuid', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'op_type', 'project_id', 'client_uuid', name='uq_offline_op_receipt_user_op_uuid')
    )
    op.create_index(op.f('ix_offline_op_receipts_user_id'), 'offline_op_receipts', ['user_id'], unique=False)
    op.create_table('project_creation_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('client_uuid', sa.String(length=64), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'client_uuid', name='uq_project_creation_user_uuid')
    )
    op.create_table('rate_limit_buckets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('bucket', sa.Integer(), nullable=False),
    sa.Column('window', sa.Integer(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'bucket', 'window', name='uq_rate_limit_user_bucket_window')
    )
    op.create_index(op.f('ix_rate_limit_buckets_user_id'), 'rate_limit_buckets', ['user_id'], unique=False)
    op.create_table('scheduler_watermarks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=50), nullable=False),
    sa.Column('last_success_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=20), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id')
    )
    op.create_table('template_docs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('stored_name', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_template_docs_task_id'), 'template_docs', ['task_id'], unique=False)
    op.create_table('template_preparation_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=True),
    sa.Column('blocks_entry', sa.Boolean(), nullable=True),
    sa.Column('owner_party', sa.String(length=20), nullable=True),
    sa.Column('risk', sa.String(length=10), nullable=True),
    sa.Column('condition', sa.String(length=20), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('template_procurement_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=True),
    sa.Column('spec', sa.String(length=300), nullable=True),
    sa.Column('due_weeks', sa.Integer(), nullable=True),
    sa.Column('condition', sa.String(length=20), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=True),
    sa.Column('owner_party', sa.String(length=20), nullable=True),
    sa.Column('risk', sa.String(length=10), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('templates',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_system', sa.Boolean(), nullable=True),
    sa.Column('vehicle_type', sa.String(length=50), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=True),
    sa.Column('snapshots', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('email', sa.String(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('token_version', sa.Integer(), nullable=True),
    sa.Column('mfa_enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('mfa_secret_encrypted', sa.Text(), nullable=True),
    sa.Column('mfa_last_step', sa.BigInteger(), server_default='-1', nullable=False),
    sa.Column('permission_overrides', sa.JSON(), nullable=True),
    sa.Column('permission_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('vehicle_steps',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('template_id', sa.String(length=36), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('template_id', 'key', name='uq_vehicle_step_template_key')
    )
    op.create_index(op.f('ix_vehicle_steps_template_id'), 'vehicle_steps', ['template_id'], unique=False)
    op.create_table('vehicle_types',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicle_types_name'), 'vehicle_types', ['name'], unique=True)
    op.create_table('ai_api_tokens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('token_prefix', sa.String(length=16), nullable=True),
    sa.Column('auth_version', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_api_tokens_token_hash'), 'ai_api_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_ai_api_tokens_user_id'), 'ai_api_tokens', ['user_id'], unique=False)
    op.create_table('document_template_files',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('stored_name', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stored_name')
    )
    op.create_table('feedback',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('steps', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_status'), 'feedback', ['status'], unique=False)
    op.create_index(op.f('ix_feedback_user_id'), 'feedback', ['user_id'], unique=False)
    op.create_table('mfa_challenges',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('login_key', sa.String(length=256), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('pending_secret_encrypted', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('mfa_recovery_codes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code_hash')
    )
    op.create_index(op.f('ix_mfa_recovery_codes_user_id'), 'mfa_recovery_codes', ['user_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('ntype', sa.String(length=30), nullable=True),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('entity_id', sa.String(length=36), nullable=True),
    sa.Column('is_read', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_table('project_permanent_backups',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('project_name', sa.String(length=200), nullable=False),
    sa.Column('deletion_id', sa.String(length=36), nullable=False),
    sa.Column('project_version', sa.Integer(), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('backup_name', sa.String(length=100), nullable=False),
    sa.Column('backup_sha256', sa.String(length=64), nullable=False),
    sa.Column('backup_bytes', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('prepared_by', sa.String(length=36), nullable=True),
    sa.Column('prepared_at', sa.DateTime(), nullable=False),
    sa.Column('purged_by', sa.String(length=36), nullable=True),
    sa.Column('purged_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['prepared_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['purged_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_permanent_backups_project_id'), 'project_permanent_backups', ['project_id'], unique=False)
    op.create_table('projects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('abbreviation', sa.String(length=50), nullable=True),
    sa.Column('contract_no', sa.String(length=100), nullable=True),
    sa.Column('manager', sa.String(length=100), nullable=True),
    sa.Column('technical_manager', sa.String(length=36), nullable=True),
    sa.Column('co_managers', sa.JSON(), nullable=True),
    sa.Column('client', sa.String(length=200), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('staffing_notes', sa.Text(), nullable=True),
    sa.Column('members', sa.JSON(), nullable=True),
    sa.Column('member_permissions', sa.JSON(), nullable=True),
    sa.Column('rest_mode', sa.String(length=10), nullable=True),
    sa.Column('rest_days', sa.JSON(), nullable=True),
    sa.Column('skip_holidays', sa.Boolean(), nullable=True),
    sa.Column('schedule_version', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('template_version', sa.Integer(), nullable=True),
    sa.Column('dispatch_platform', sa.String(length=20), nullable=True),
    sa.Column('readiness_state', sa.String(length=20), nullable=True),
    sa.Column('prep_conditions', sa.JSON(), nullable=True),
    sa.Column('prep_confirmed_by', sa.String(length=36), nullable=True),
    sa.Column('prep_confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('prep_conclusion', sa.Text(), nullable=True),
    sa.Column('client_contacts', sa.JSON(), nullable=True),
    sa.Column('entry_plan', sa.JSON(), nullable=True),
    sa.Column('suspension', sa.JSON(), nullable=True),
    sa.Column('retrospective', sa.JSON(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("status IN ('preparing','executing','acceptance','completed','archived','suspended')", name='ck_project_status'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('template_sections',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('stage_key', sa.String(length=8), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_template_sections_template_id'), 'template_sections', ['template_id'], unique=False)
    op.create_table('acceptance_records',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('accepted_by', sa.String(length=36), nullable=True),
    sa.Column('accepted_by_name', sa.String(length=100), nullable=True),
    sa.Column('accepted_at', sa.Date(), nullable=False),
    sa.Column('scope_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('conclusion', sa.String(length=30), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('attachment_id', sa.String(length=36), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['accepted_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_acceptance_records_project_id'), 'acceptance_records', ['project_id'], unique=False)
    op.create_table('attachments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('entity_type', sa.String(length=50), nullable=True),
    sa.Column('entity_id', sa.String(length=36), nullable=True),
    sa.Column('category', sa.String(length=50), nullable=True),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('stored_name', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True),
    sa.Column('confidential', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('confidential_explicit', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('confidential_user_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False),
    sa.Column('access_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_attachments_project_id'), 'attachments', ['project_id'], unique=False)
    op.create_table('change_logs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('entity_type', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('operator_id', sa.String(length=36), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('old_value', sa.JSON(), nullable=True),
    sa.Column('new_value', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_change_logs_project_id'), 'change_logs', ['project_id'], unique=False)
    op.create_table('document_requirements',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('stage_key', sa.String(length=8), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('template_no', sa.String(length=100), nullable=True),
    sa.Column('is_group', sa.Boolean(), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=True),
    sa.Column('platform', sa.String(length=20), nullable=True),
    sa.Column('timing_type', sa.String(length=24), nullable=True),
    sa.Column('timing_event', sa.String(length=32), nullable=True),
    sa.Column('timing_offset_hours', sa.Integer(), nullable=True),
    sa.Column('timing_weekday', sa.Integer(), nullable=True),
    sa.Column('trigger_type', sa.String(length=20), nullable=True),
    sa.Column('confidential_default', sa.Boolean(), nullable=False),
    sa.Column('external_visible_default', sa.Boolean(), nullable=False),
    sa.Column('external_never_visible', sa.Boolean(), nullable=False),
    sa.Column('blank_file_id', sa.String(length=36), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source_metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['blank_file_id'], ['document_template_files.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['parent_id'], ['document_requirements.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_requirements_template_id'), 'document_requirements', ['template_id'], unique=False)
    op.create_index('uq_document_requirement_default_code', 'document_requirements', ['code'], unique=True, sqlite_where=sa.text('template_id IS NULL'), postgresql_where=sa.text('template_id IS NULL'))
    op.create_index('uq_document_requirement_template_code', 'document_requirements', ['template_id', 'code'], unique=True, sqlite_where=sa.text('template_id IS NOT NULL'), postgresql_where=sa.text('template_id IS NOT NULL'))
    op.create_table('document_trigger_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('trigger_type', sa.String(length=20), nullable=False),
    sa.Column('source_type', sa.String(length=30), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=False),
    sa.Column('source_key', sa.String(length=160), nullable=False),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('source_metadata', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'source_key', name='uq_document_trigger_source')
    )
    op.create_index(op.f('ix_document_trigger_events_project_id'), 'document_trigger_events', ['project_id'], unique=False)
    op.create_table('external_shares',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=False),
    sa.Column('document_ids', sa.JSON(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_external_shares_project_id'), 'external_shares', ['project_id'], unique=False)
    op.create_table('field_operations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('target_id', sa.String(length=36), nullable=False),
    sa.Column('step_key', sa.String(length=80), nullable=False),
    sa.Column('weekly_cell_id', sa.String(length=36), nullable=True),
    sa.Column('target_label', sa.String(length=400), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('assisted_user_id', sa.String(length=36), nullable=True),
    sa.Column('completion_date', sa.Date(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(), nullable=False),
    sa.Column('is_done', sa.Boolean(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('replaces_id', sa.String(length=36), nullable=True),
    sa.Column('root_id', sa.String(length=36), nullable=True),
    sa.Column('restores_id', sa.String(length=36), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('before_state', sa.JSON(), nullable=False),
    sa.Column('after_version', sa.Integer(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('client_uuid', sa.String(length=64), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['assisted_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'actor_id', 'client_uuid', name='uq_field_operation_actor_uuid'),
    sa.UniqueConstraint('project_id', 'sequence', name='uq_field_operation_sequence')
    )
    op.create_index(op.f('ix_field_operations_actor_id'), 'field_operations', ['actor_id'], unique=False)
    op.create_index(op.f('ix_field_operations_project_id'), 'field_operations', ['project_id'], unique=False)
    op.create_table('file_cleanup_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('actor_name', sa.String(length=100), nullable=False),
    sa.Column('keep_periods', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('preview_sha256', sa.String(length=64), nullable=False),
    sa.Column('policy', sa.JSON(), nullable=False),
    sa.Column('applied_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_file_cleanup_receipts_project_id'), 'file_cleanup_receipts', ['project_id'], unique=False)
    op.create_table('item_applications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=True),
    sa.Column('item_name', sa.String(length=200), nullable=True),
    sa.Column('requirement', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('drawing_no', sa.String(length=100), nullable=True),
    sa.Column('contract_no', sa.String(length=100), nullable=True),
    sa.Column('amount', sa.String(length=100), nullable=True),
    sa.Column('applicant', sa.String(length=100), nullable=True),
    sa.Column('approver', sa.String(length=100), nullable=True),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('apply_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_item_applications_project_id'), 'item_applications', ['project_id'], unique=False)
    op.create_table('phases',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.Column('color', sa.String(length=20), nullable=True),
    sa.Column('entry_criteria', sa.Text(), nullable=True),
    sa.Column('exit_criteria', sa.Text(), nullable=True),
    sa.Column('stage_key', sa.String(length=10), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_phases_project_id'), 'phases', ['project_id'], unique=False)
    op.create_index(op.f('ix_phases_template_id'), 'phases', ['template_id'], unique=False)
    op.create_table('project_deletion_records',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('deleted_by', sa.String(length=36), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=False),
    sa.Column('status_before_delete', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('backup_name', sa.String(length=100), nullable=False),
    sa.Column('backup_sha256', sa.String(length=64), nullable=False),
    sa.Column('backup_bytes', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('protected_from_purge', sa.Boolean(), nullable=False),
    sa.Column('restored_by', sa.String(length=36), nullable=True),
    sa.Column('restored_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['deleted_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['restored_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_deletion_records_deleted_at'), 'project_deletion_records', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_project_deletion_records_project_id'), 'project_deletion_records', ['project_id'], unique=False)
    op.create_table('project_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('event_key', sa.String(length=32), nullable=False),
    sa.Column('planned_date', sa.Date(), nullable=True),
    sa.Column('actual_at', sa.DateTime(), nullable=True),
    sa.Column('actual_date', sa.Date(), nullable=True),
    sa.Column('actual_source', sa.JSON(), nullable=True),
    sa.Column('recorded_by', sa.String(length=36), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.CheckConstraint("event_key IN ('internal_kickoff','ship','arrival_all','delivery_signed','commissioning_done','go_live','training_done','acceptance','handover')", name='ck_project_event_key'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'event_key', name='uq_project_event_key')
    )
    op.create_index(op.f('ix_project_events_project_id'), 'project_events', ['project_id'], unique=False)
    op.create_table('project_inventory_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('item_code', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=True),
    sa.Column('ownership', sa.String(length=20), nullable=False),
    sa.Column('tracking_mode', sa.String(length=20), nullable=True),
    sa.Column('specification', sa.String(length=300), nullable=True),
    sa.Column('serial_number', sa.String(length=200), nullable=True),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('minimum_quantity', sa.Float(), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('custodian', sa.String(length=100), nullable=True),
    sa.Column('supplier', sa.String(length=200), nullable=True),
    sa.Column('received_date', sa.Date(), nullable=True),
    sa.Column('expected_return_date', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_inventory_items_item_code'), 'project_inventory_items', ['item_code'], unique=False)
    op.create_index(op.f('ix_project_inventory_items_name'), 'project_inventory_items', ['name'], unique=False)
    op.create_index(op.f('ix_project_inventory_items_project_id'), 'project_inventory_items', ['project_id'], unique=False)
    op.create_table('project_members',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'user_id', name='uq_project_member')
    )
    op.create_index(op.f('ix_project_members_project_id'), 'project_members', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_members_user_id'), 'project_members', ['user_id'], unique=False)
    op.create_table('project_preparation_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=True),
    sa.Column('blocks_entry', sa.Boolean(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.Column('owner_party', sa.String(length=20), nullable=True),
    sa.Column('required_date', sa.Date(), nullable=True),
    sa.Column('committed_date', sa.Date(), nullable=True),
    sa.Column('forecast_date', sa.Date(), nullable=True),
    sa.Column('planned_date', sa.Date(), nullable=True),
    sa.Column('actual_date', sa.Date(), nullable=True),
    sa.Column('risk', sa.String(length=10), nullable=True),
    sa.Column('affected_phase_id', sa.String(length=36), nullable=True),
    sa.Column('affected_task_id', sa.String(length=36), nullable=True),
    sa.Column('completed_by', sa.String(length=36), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_preparation_items_project_id'), 'project_preparation_items', ['project_id'], unique=False)
    op.create_table('project_readiness_reviews',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('conclusion', sa.String(length=20), nullable=False),
    sa.Column('reviewer_id', sa.String(length=36), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('remaining_risks', sa.JSON(), nullable=True),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_readiness_reviews_project_id'), 'project_readiness_reviews', ['project_id'], unique=False)
    op.create_table('project_report_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('period_key', sa.String(length=10), nullable=False),
    sa.Column('delivery_pending', sa.Boolean(), nullable=False),
    sa.Column('recipient_id', sa.String(length=36), nullable=True),
    sa.Column('delivered_at', sa.DateTime(), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'period_key', name='uq_project_weekly_report')
    )
    op.create_index(op.f('ix_project_report_receipts_project_id'), 'project_report_receipts', ['project_id'], unique=False)
    op.create_table('template_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('section_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('optional', sa.Boolean(), nullable=False),
    sa.Column('per_vehicle', sa.Boolean(), nullable=False),
    sa.Column('step_key', sa.String(length=80), nullable=True),
    sa.Column('checks', sa.JSON(), nullable=False),
    sa.Column('files', sa.JSON(), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.Column('spec', sa.String(length=300), nullable=False),
    sa.Column('extra', sa.JSON(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['section_id'], ['template_sections.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_template_items_section_id'), 'template_items', ['section_id'], unique=False)
    op.create_index(op.f('ix_template_items_template_id'), 'template_items', ['template_id'], unique=False)
    op.create_table('vehicles',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_type', sa.String(length=50), nullable=False),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('configuration', sa.JSON(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicles_project_id'), 'vehicles', ['project_id'], unique=False)
    op.create_table('external_access_logs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('share_id', sa.String(length=36), nullable=True),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('resource_id', sa.String(length=36), nullable=True),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['share_id'], ['external_shares.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_external_access_logs_project_id'), 'external_access_logs', ['project_id'], unique=False)
    op.create_index(op.f('ix_external_access_logs_share_id'), 'external_access_logs', ['share_id'], unique=False)
    op.create_table('file_removal_records',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('attachment_id', sa.String(length=36), nullable=False),
    sa.Column('receipt_id', sa.String(length=36), nullable=False),
    sa.Column('stored_name', sa.String(length=100), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('file_size', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('removed_at', sa.DateTime(), nullable=False),
    sa.Column('removed_by', sa.String(length=36), nullable=True),
    sa.Column('removed_by_name', sa.String(length=100), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['attachment_id'], ['attachments.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['receipt_id'], ['file_cleanup_receipts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['removed_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('attachment_id')
    )
    op.create_index(op.f('ix_file_removal_records_project_id'), 'file_removal_records', ['project_id'], unique=False)
    op.create_table('modules',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('source_module_id', sa.String(length=36), nullable=True),
    sa.Column('phase_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=True),
    sa.Column('is_selected', sa.Boolean(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('preparation_conditions', sa.JSON(), nullable=True),
    sa.Column('applies_to_all_vehicles', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['phase_id'], ['phases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_modules_project_id'), 'modules', ['project_id'], unique=False)
    op.create_index(op.f('ix_modules_source_module_id'), 'modules', ['source_module_id'], unique=False)
    op.create_index(op.f('ix_modules_template_id'), 'modules', ['template_id'], unique=False)
    op.create_table('project_document_definitions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('requirement_id', sa.String(length=36), nullable=True),
    sa.Column('source_key', sa.String(length=160), nullable=False),
    sa.Column('confidential_default', sa.Boolean(), nullable=False),
    sa.Column('confidential_user_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False),
    sa.Column('access_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('external_visible_default', sa.Boolean(), nullable=False),
    sa.Column('external_never_visible', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('stage_key', sa.String(length=8), nullable=False),
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('template_no', sa.String(length=100), nullable=True),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('platform', sa.String(length=20), nullable=True),
    sa.Column('timing_type', sa.String(length=24), nullable=False),
    sa.Column('timing_event', sa.String(length=32), nullable=True),
    sa.Column('timing_offset_hours', sa.Integer(), nullable=True),
    sa.Column('timing_weekday', sa.Integer(), nullable=True),
    sa.Column('trigger_type', sa.String(length=20), nullable=True),
    sa.Column('blank_file_id', sa.String(length=36), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source_metadata', sa.JSON(), nullable=True),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['blank_file_id'], ['document_template_files.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_id'], ['document_requirements.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'source_key', name='uq_project_document_definition_source')
    )
    op.create_index(op.f('ix_project_document_definitions_project_id'), 'project_document_definitions', ['project_id'], unique=False)
    op.create_table('project_inventory_movements',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('item_id', sa.String(length=36), nullable=False),
    sa.Column('movement_type', sa.String(length=30), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('balance_after', sa.Float(), nullable=False),
    sa.Column('from_location', sa.String(length=200), nullable=True),
    sa.Column('to_location', sa.String(length=200), nullable=True),
    sa.Column('handler', sa.String(length=100), nullable=True),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('operator_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['project_inventory_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_inventory_movements_item_id'), 'project_inventory_movements', ['item_id'], unique=False)
    op.create_index(op.f('ix_project_inventory_movements_project_id'), 'project_inventory_movements', ['project_id'], unique=False)
    op.create_table('upload_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.Column('client_uuid', sa.String(length=64), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('size', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('chunk_size', sa.Integer(), nullable=False),
    sa.Column('document_ids', sa.JSON(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.String(length=20), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('confidential', sa.Boolean(), nullable=False),
    sa.Column('confidential_user_ids', sa.JSON(), nullable=False),
    sa.Column('milestone_dates', sa.JSON(), nullable=False),
    sa.Column('attachment_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['attachment_id'], ['attachments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'client_uuid', name='uq_upload_owner_intent')
    )
    op.create_index(op.f('ix_upload_sessions_project_id'), 'upload_sessions', ['project_id'], unique=False)
    op.create_table('vehicle_units',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_id', sa.String(length=36), nullable=True),
    sa.Column('asset_code', sa.String(length=100), nullable=False),
    sa.Column('serial_number', sa.String(length=100), nullable=True),
    sa.Column('fleet_no', sa.String(length=30), nullable=True),
    sa.Column('frame_no', sa.String(length=100), nullable=True),
    sa.Column('factory_date', sa.Date(), nullable=True),
    sa.Column('model_name', sa.String(length=100), nullable=True),
    sa.Column('current_stage', sa.String(length=80), nullable=True),
    sa.Column('current_status', sa.String(length=30), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('warranty_end', sa.Date(), nullable=True),
    sa.Column('commissioned_at', sa.Date(), nullable=True),
    sa.Column('arrived_at', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'asset_code', name='uq_vehicle_unit_asset')
    )
    op.create_index(op.f('ix_vehicle_units_project_id'), 'vehicle_units', ['project_id'], unique=False)
    op.create_index(op.f('ix_vehicle_units_vehicle_id'), 'vehicle_units', ['vehicle_id'], unique=False)
    op.create_table('project_documents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('definition_id', sa.String(length=36), nullable=True),
    sa.Column('requirement_id', sa.String(length=36), nullable=True),
    sa.Column('instance_key', sa.String(length=250), nullable=False),
    sa.Column('vehicle_unit_id', sa.String(length=36), nullable=True),
    sa.Column('vehicle_label', sa.String(length=200), nullable=True),
    sa.Column('period_key', sa.String(length=32), nullable=True),
    sa.Column('trigger_ref', sa.String(length=100), nullable=True),
    sa.Column('due_at', sa.DateTime(), nullable=True),
    sa.Column('due_is_estimated', sa.Boolean(), nullable=False),
    sa.Column('due_basis', sa.JSON(), nullable=True),
    sa.Column('triggered_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('waived_reason', sa.Text(), nullable=True),
    sa.Column('confidential', sa.Boolean(), nullable=False),
    sa.Column('confidential_user_ids', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), server_default='[]', nullable=False),
    sa.Column('external_visible', sa.Boolean(), nullable=False),
    sa.Column('external_never_visible', sa.Boolean(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(), nullable=True),
    sa.Column('submitted_by', sa.String(length=36), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('stage_key', sa.String(length=8), nullable=False),
    sa.Column('code', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('template_no', sa.String(length=100), nullable=True),
    sa.Column('required', sa.Boolean(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('platform', sa.String(length=20), nullable=True),
    sa.Column('timing_type', sa.String(length=24), nullable=False),
    sa.Column('timing_event', sa.String(length=32), nullable=True),
    sa.Column('timing_offset_hours', sa.Integer(), nullable=True),
    sa.Column('timing_weekday', sa.Integer(), nullable=True),
    sa.Column('trigger_type', sa.String(length=20), nullable=True),
    sa.Column('blank_file_id', sa.String(length=36), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source_metadata', sa.JSON(), nullable=True),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.CheckConstraint("status IN ('pending','submitted','waived')", name='ck_project_document_status'),
    sa.ForeignKeyConstraint(['blank_file_id'], ['document_template_files.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['definition_id'], ['project_document_definitions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_id'], ['document_requirements.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_unit_id'], ['vehicle_units.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'instance_key', name='uq_project_document_instance')
    )
    op.create_index(op.f('ix_project_documents_project_id'), 'project_documents', ['project_id'], unique=False)
    op.create_table('upload_chunks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('received_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['upload_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_id', 'chunk_index', name='uq_upload_chunk_index')
    )
    op.create_index(op.f('ix_upload_chunks_project_id'), 'upload_chunks', ['project_id'], unique=False)
    op.create_index(op.f('ix_upload_chunks_session_id'), 'upload_chunks', ['session_id'], unique=False)
    op.create_table('vehicle_lifecycle_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_unit_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('event_type', sa.String(length=30), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('fault_part', sa.String(length=200), nullable=True),
    sa.Column('cause', sa.Text(), nullable=True),
    sa.Column('action_taken', sa.Text(), nullable=True),
    sa.Column('replaced_parts', sa.JSON(), nullable=True),
    sa.Column('downtime_hours', sa.Float(), nullable=True),
    sa.Column('verification', sa.Text(), nullable=True),
    sa.Column('handler', sa.String(length=100), nullable=True),
    sa.Column('is_closed', sa.Boolean(), nullable=True),
    sa.Column('stage_after', sa.String(length=30), nullable=True),
    sa.Column('status_after', sa.String(length=30), nullable=True),
    sa.Column('location_after', sa.String(length=200), nullable=True),
    sa.Column('attachment_id', sa.String(length=36), nullable=True),
    sa.Column('operator_id', sa.String(length=36), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=True),
    sa.Column('import_key', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_unit_id'], ['vehicle_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicle_lifecycle_events_import_key'), 'vehicle_lifecycle_events', ['import_key'], unique=False)
    op.create_index(op.f('ix_vehicle_lifecycle_events_project_id'), 'vehicle_lifecycle_events', ['project_id'], unique=False)
    op.create_index(op.f('ix_vehicle_lifecycle_events_vehicle_unit_id'), 'vehicle_lifecycle_events', ['vehicle_unit_id'], unique=False)
    op.create_table('vehicle_progress',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_unit_id', sa.String(length=36), nullable=False),
    sa.Column('step_key', sa.String(length=80), nullable=False),
    sa.Column('is_done', sa.Boolean(), nullable=False),
    sa.Column('done_on', sa.Date(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(), nullable=False),
    sa.Column('done_by', sa.String(length=36), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('source_metadata', sa.JSON(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['done_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_unit_id'], ['vehicle_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('vehicle_unit_id', 'step_key', name='uq_vehicle_progress_unit_step')
    )
    op.create_index(op.f('ix_vehicle_progress_project_id'), 'vehicle_progress', ['project_id'], unique=False)
    op.create_index(op.f('ix_vehicle_progress_vehicle_unit_id'), 'vehicle_progress', ['vehicle_unit_id'], unique=False)
    op.create_table('document_notice_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('project_document_id', sa.String(length=36), nullable=False),
    sa.Column('recipient_id', sa.String(length=36), nullable=True),
    sa.Column('recipient_key', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=False),
    sa.Column('due_is_estimated', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_document_id'], ['project_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_document_id', 'recipient_key', 'kind', 'due_at', 'due_is_estimated', name='uq_document_notice_revision')
    )
    op.create_index(op.f('ix_document_notice_receipts_project_id'), 'document_notice_receipts', ['project_id'], unique=False)
    op.create_table('document_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_document_id', sa.String(length=36), nullable=False),
    sa.Column('attachment_id', sa.String(length=36), nullable=False),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('review_metadata', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['attachment_id'], ['attachments.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_document_id'], ['project_documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_versions_attachment_id'), 'document_versions', ['attachment_id'], unique=False)
    op.create_index(op.f('ix_document_versions_project_document_id'), 'document_versions', ['project_document_id'], unique=False)
    op.create_table('tasks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('module_id', sa.String(length=36), nullable=True),
    sa.Column('phase_id', sa.String(length=36), nullable=True),
    sa.Column('group_label', sa.String(length=200), nullable=True),
    sa.Column('scope_conditions', sa.JSON(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('quantity_type', sa.String(length=20), nullable=False),
    sa.Column('safety_flag', sa.Boolean(), nullable=True),
    sa.Column('applicable_vehicle_types', sa.JSON(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.Column('reference_docs', sa.JSON(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('source_task_id', sa.String(length=36), nullable=True),
    sa.Column('vehicle_step_key', sa.String(length=80), nullable=True),
    sa.Column('source_vehicle_event_id', sa.String(length=36), nullable=True),
    sa.Column('manually_completed', sa.Boolean(), nullable=True),
    sa.Column('manual_completed_by', sa.String(length=36), nullable=True),
    sa.Column('manual_completed_role', sa.String(length=20), nullable=True),
    sa.Column('manual_completed_at', sa.DateTime(), nullable=True),
    sa.Column('manual_completed_reason', sa.Text(), nullable=True),
    sa.Column('manual_check_overrides', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['phase_id'], ['phases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_vehicle_event_id'], ['vehicle_lifecycle_events.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_vehicle_event_id')
    )
    op.create_index(op.f('ix_tasks_module_id'), 'tasks', ['module_id'], unique=False)
    op.create_index(op.f('ix_tasks_phase_id'), 'tasks', ['phase_id'], unique=False)
    op.create_index(op.f('ix_tasks_project_id'), 'tasks', ['project_id'], unique=False)
    op.create_index(op.f('ix_tasks_source_task_id'), 'tasks', ['source_task_id'], unique=False)
    op.create_index(op.f('ix_tasks_template_id'), 'tasks', ['template_id'], unique=False)
    op.create_table('issues',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('issue_type', sa.String(length=20), nullable=True),
    sa.Column('nature', sa.String(length=20), server_default='normal', nullable=False),
    sa.Column('source_metadata', sa.JSON(), nullable=True),
    sa.Column('severity', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('reporter_id', sa.String(length=36), nullable=False),
    sa.Column('assignee_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolution', sa.Text(), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('client_uuid', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'client_uuid', name='uq_issue_project_client_uuid')
    )
    op.create_index(op.f('ix_issues_project_id'), 'issues', ['project_id'], unique=False)
    op.create_table('project_vehicle_steps',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('source_task_id', sa.String(length=36), nullable=True),
    sa.Column('expected_quantity', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'key', name='uq_project_vehicle_step_key')
    )
    op.create_index(op.f('ix_project_vehicle_steps_project_id'), 'project_vehicle_steps', ['project_id'], unique=False)
    op.create_table('vehicle_check_definitions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('source_check_id', sa.String(length=36), nullable=False),
    sa.Column('source_version', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_safety_critical', sa.Boolean(), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'source_check_id', name='uq_vehicle_check_definition_source')
    )
    op.create_index(op.f('ix_vehicle_check_definitions_project_id'), 'vehicle_check_definitions', ['project_id'], unique=False)
    op.create_index(op.f('ix_vehicle_check_definitions_task_id'), 'vehicle_check_definitions', ['task_id'], unique=False)
    op.create_table('weekly_plan_cells',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('scope_key', sa.String(length=160), nullable=False),
    sa.Column('scope', sa.JSON(), nullable=False),
    sa.Column('vehicle_step_key', sa.String(length=80), nullable=True),
    sa.Column('week_start', sa.Date(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('target_count', sa.Integer(), nullable=True),
    sa.Column('intent_review_required', sa.Boolean(), nullable=False),
    sa.Column('assignee_ids', sa.JSON(), nullable=False),
    sa.Column('published', sa.Boolean(), nullable=False),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('published_by', sa.String(length=36), nullable=True),
    sa.Column('is_cancelled', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('source_metadata', sa.JSON(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.CheckConstraint("mode IN ('finish','in_progress')", name='ck_weekly_plan_mode'),
    sa.CheckConstraint('target_count IS NULL OR target_count > 0', name='ck_weekly_plan_positive_target'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['published_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'task_id', 'scope_key', 'week_start', name='uq_weekly_plan_work_scope_week')
    )
    op.create_index(op.f('ix_weekly_plan_cells_project_id'), 'weekly_plan_cells', ['project_id'], unique=False)
    op.create_index(op.f('ix_weekly_plan_cells_task_id'), 'weekly_plan_cells', ['task_id'], unique=False)
    op.create_index(op.f('ix_weekly_plan_cells_week_start'), 'weekly_plan_cells', ['week_start'], unique=False)
    op.create_table('check_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_safety_critical', sa.Boolean(), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=True),
    sa.Column('is_applicable', sa.Boolean(), nullable=True),
    sa.Column('not_applicable_reason', sa.Text(), nullable=True),
    sa.Column('not_applicable_set_by', sa.String(length=36), nullable=True),
    sa.Column('not_applicable_set_at', sa.DateTime(), nullable=True),
    sa.Column('is_done', sa.Boolean(), nullable=True),
    sa.Column('done_by', sa.String(length=36), nullable=True),
    sa.Column('done_at', sa.DateTime(), nullable=True),
    sa.Column('failed', sa.Boolean(), nullable=True),
    sa.Column('failed_reason', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('vehicle_unit_id', sa.String(length=36), nullable=True),
    sa.Column('vehicle_step_key', sa.String(length=80), nullable=True),
    sa.Column('vehicle_check_definition_id', sa.String(length=36), nullable=True),
    sa.Column('definition_version', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_check_definition_id'], ['vehicle_check_definitions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_unit_id'], ['vehicle_units.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('vehicle_unit_id', 'vehicle_check_definition_id', name='uq_vehicle_check_unit_definition')
    )
    op.create_index(op.f('ix_check_items_project_id'), 'check_items', ['project_id'], unique=False)
    op.create_index(op.f('ix_check_items_task_id'), 'check_items', ['task_id'], unique=False)
    op.create_index(op.f('ix_check_items_template_id'), 'check_items', ['template_id'], unique=False)
    op.create_index(op.f('ix_check_items_vehicle_check_definition_id'), 'check_items', ['vehicle_check_definition_id'], unique=False)
    op.create_index(op.f('ix_check_items_vehicle_unit_id'), 'check_items', ['vehicle_unit_id'], unique=False)
    op.create_table('issue_sla_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('issue_id', sa.String(length=36), nullable=False),
    sa.Column('nature', sa.String(length=20), nullable=False),
    sa.Column('sla_hours', sa.Integer(), nullable=False),
    sa.Column('recipient_id', sa.String(length=36), nullable=True),
    sa.Column('recipient_key', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('issue_id', 'nature', 'sla_hours', 'recipient_key', name='uq_issue_sla_delivery')
    )
    op.create_index(op.f('ix_issue_sla_receipts_project_id'), 'issue_sla_receipts', ['project_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_issue_sla_receipts_project_id'), table_name='issue_sla_receipts')
    op.drop_table('issue_sla_receipts')
    op.drop_index(op.f('ix_check_items_vehicle_unit_id'), table_name='check_items')
    op.drop_index(op.f('ix_check_items_vehicle_check_definition_id'), table_name='check_items')
    op.drop_index(op.f('ix_check_items_template_id'), table_name='check_items')
    op.drop_index(op.f('ix_check_items_task_id'), table_name='check_items')
    op.drop_index(op.f('ix_check_items_project_id'), table_name='check_items')
    op.drop_table('check_items')
    op.drop_index(op.f('ix_weekly_plan_cells_week_start'), table_name='weekly_plan_cells')
    op.drop_index(op.f('ix_weekly_plan_cells_task_id'), table_name='weekly_plan_cells')
    op.drop_index(op.f('ix_weekly_plan_cells_project_id'), table_name='weekly_plan_cells')
    op.drop_table('weekly_plan_cells')
    op.drop_index(op.f('ix_vehicle_check_definitions_task_id'), table_name='vehicle_check_definitions')
    op.drop_index(op.f('ix_vehicle_check_definitions_project_id'), table_name='vehicle_check_definitions')
    op.drop_table('vehicle_check_definitions')
    op.drop_index(op.f('ix_project_vehicle_steps_project_id'), table_name='project_vehicle_steps')
    op.drop_table('project_vehicle_steps')
    op.drop_index(op.f('ix_issues_project_id'), table_name='issues')
    op.drop_table('issues')
    op.drop_index(op.f('ix_tasks_template_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_source_task_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_project_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_phase_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_module_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_document_versions_project_document_id'), table_name='document_versions')
    op.drop_index(op.f('ix_document_versions_attachment_id'), table_name='document_versions')
    op.drop_table('document_versions')
    op.drop_index(op.f('ix_document_notice_receipts_project_id'), table_name='document_notice_receipts')
    op.drop_table('document_notice_receipts')
    op.drop_index(op.f('ix_vehicle_progress_vehicle_unit_id'), table_name='vehicle_progress')
    op.drop_index(op.f('ix_vehicle_progress_project_id'), table_name='vehicle_progress')
    op.drop_table('vehicle_progress')
    op.drop_index(op.f('ix_vehicle_lifecycle_events_vehicle_unit_id'), table_name='vehicle_lifecycle_events')
    op.drop_index(op.f('ix_vehicle_lifecycle_events_project_id'), table_name='vehicle_lifecycle_events')
    op.drop_index(op.f('ix_vehicle_lifecycle_events_import_key'), table_name='vehicle_lifecycle_events')
    op.drop_table('vehicle_lifecycle_events')
    op.drop_index(op.f('ix_upload_chunks_session_id'), table_name='upload_chunks')
    op.drop_index(op.f('ix_upload_chunks_project_id'), table_name='upload_chunks')
    op.drop_table('upload_chunks')
    op.drop_index(op.f('ix_project_documents_project_id'), table_name='project_documents')
    op.drop_table('project_documents')
    op.drop_index(op.f('ix_vehicle_units_vehicle_id'), table_name='vehicle_units')
    op.drop_index(op.f('ix_vehicle_units_project_id'), table_name='vehicle_units')
    op.drop_table('vehicle_units')
    op.drop_index(op.f('ix_upload_sessions_project_id'), table_name='upload_sessions')
    op.drop_table('upload_sessions')
    op.drop_index(op.f('ix_project_inventory_movements_project_id'), table_name='project_inventory_movements')
    op.drop_index(op.f('ix_project_inventory_movements_item_id'), table_name='project_inventory_movements')
    op.drop_table('project_inventory_movements')
    op.drop_index(op.f('ix_project_document_definitions_project_id'), table_name='project_document_definitions')
    op.drop_table('project_document_definitions')
    op.drop_index(op.f('ix_modules_template_id'), table_name='modules')
    op.drop_index(op.f('ix_modules_source_module_id'), table_name='modules')
    op.drop_index(op.f('ix_modules_project_id'), table_name='modules')
    op.drop_table('modules')
    op.drop_index(op.f('ix_file_removal_records_project_id'), table_name='file_removal_records')
    op.drop_table('file_removal_records')
    op.drop_index(op.f('ix_external_access_logs_share_id'), table_name='external_access_logs')
    op.drop_index(op.f('ix_external_access_logs_project_id'), table_name='external_access_logs')
    op.drop_table('external_access_logs')
    op.drop_index(op.f('ix_vehicles_project_id'), table_name='vehicles')
    op.drop_table('vehicles')
    op.drop_index(op.f('ix_template_items_template_id'), table_name='template_items')
    op.drop_index(op.f('ix_template_items_section_id'), table_name='template_items')
    op.drop_table('template_items')
    op.drop_index(op.f('ix_project_report_receipts_project_id'), table_name='project_report_receipts')
    op.drop_table('project_report_receipts')
    op.drop_index(op.f('ix_project_readiness_reviews_project_id'), table_name='project_readiness_reviews')
    op.drop_table('project_readiness_reviews')
    op.drop_index(op.f('ix_project_preparation_items_project_id'), table_name='project_preparation_items')
    op.drop_table('project_preparation_items')
    op.drop_index(op.f('ix_project_members_user_id'), table_name='project_members')
    op.drop_index(op.f('ix_project_members_project_id'), table_name='project_members')
    op.drop_table('project_members')
    op.drop_index(op.f('ix_project_inventory_items_project_id'), table_name='project_inventory_items')
    op.drop_index(op.f('ix_project_inventory_items_name'), table_name='project_inventory_items')
    op.drop_index(op.f('ix_project_inventory_items_item_code'), table_name='project_inventory_items')
    op.drop_table('project_inventory_items')
    op.drop_index(op.f('ix_project_events_project_id'), table_name='project_events')
    op.drop_table('project_events')
    op.drop_index(op.f('ix_project_deletion_records_project_id'), table_name='project_deletion_records')
    op.drop_index(op.f('ix_project_deletion_records_deleted_at'), table_name='project_deletion_records')
    op.drop_table('project_deletion_records')
    op.drop_index(op.f('ix_phases_template_id'), table_name='phases')
    op.drop_index(op.f('ix_phases_project_id'), table_name='phases')
    op.drop_table('phases')
    op.drop_index(op.f('ix_item_applications_project_id'), table_name='item_applications')
    op.drop_table('item_applications')
    op.drop_index(op.f('ix_file_cleanup_receipts_project_id'), table_name='file_cleanup_receipts')
    op.drop_table('file_cleanup_receipts')
    op.drop_index(op.f('ix_field_operations_project_id'), table_name='field_operations')
    op.drop_index(op.f('ix_field_operations_actor_id'), table_name='field_operations')
    op.drop_table('field_operations')
    op.drop_index(op.f('ix_external_shares_project_id'), table_name='external_shares')
    op.drop_table('external_shares')
    op.drop_index(op.f('ix_document_trigger_events_project_id'), table_name='document_trigger_events')
    op.drop_table('document_trigger_events')
    op.drop_index('uq_document_requirement_template_code', table_name='document_requirements', sqlite_where=sa.text('template_id IS NOT NULL'), postgresql_where=sa.text('template_id IS NOT NULL'))
    op.drop_index('uq_document_requirement_default_code', table_name='document_requirements', sqlite_where=sa.text('template_id IS NULL'), postgresql_where=sa.text('template_id IS NULL'))
    op.drop_index(op.f('ix_document_requirements_template_id'), table_name='document_requirements')
    op.drop_table('document_requirements')
    op.drop_index(op.f('ix_change_logs_project_id'), table_name='change_logs')
    op.drop_table('change_logs')
    op.drop_index(op.f('ix_attachments_project_id'), table_name='attachments')
    op.drop_table('attachments')
    op.drop_index(op.f('ix_acceptance_records_project_id'), table_name='acceptance_records')
    op.drop_table('acceptance_records')
    op.drop_index(op.f('ix_template_sections_template_id'), table_name='template_sections')
    op.drop_table('template_sections')
    op.drop_table('projects')
    op.drop_index(op.f('ix_project_permanent_backups_project_id'), table_name='project_permanent_backups')
    op.drop_table('project_permanent_backups')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_mfa_recovery_codes_user_id'), table_name='mfa_recovery_codes')
    op.drop_table('mfa_recovery_codes')
    op.drop_table('mfa_challenges')
    op.drop_index(op.f('ix_feedback_user_id'), table_name='feedback')
    op.drop_index(op.f('ix_feedback_status'), table_name='feedback')
    op.drop_table('feedback')
    op.drop_table('document_template_files')
    op.drop_index(op.f('ix_ai_api_tokens_user_id'), table_name='ai_api_tokens')
    op.drop_index(op.f('ix_ai_api_tokens_token_hash'), table_name='ai_api_tokens')
    op.drop_table('ai_api_tokens')
    op.drop_index(op.f('ix_vehicle_types_name'), table_name='vehicle_types')
    op.drop_table('vehicle_types')
    op.drop_index(op.f('ix_vehicle_steps_template_id'), table_name='vehicle_steps')
    op.drop_table('vehicle_steps')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_table('templates')
    op.drop_table('template_procurement_items')
    op.drop_table('template_preparation_items')
    op.drop_index(op.f('ix_template_docs_task_id'), table_name='template_docs')
    op.drop_table('template_docs')
    op.drop_table('scheduler_watermarks')
    op.drop_index(op.f('ix_rate_limit_buckets_user_id'), table_name='rate_limit_buckets')
    op.drop_table('rate_limit_buckets')
    op.drop_table('project_creation_receipts')
    op.drop_index(op.f('ix_offline_op_receipts_user_id'), table_name='offline_op_receipts')
    op.drop_table('offline_op_receipts')
    op.drop_index(op.f('ix_notification_outbox_status'), table_name='notification_outbox')
    op.drop_index(op.f('ix_notification_outbox_next_retry_at'), table_name='notification_outbox')
    op.drop_index(op.f('ix_notification_outbox_idempotency_key'), table_name='notification_outbox')
    op.drop_table('notification_outbox')
    op.drop_index(op.f('ix_notification_channel_configs_channel'), table_name='notification_channel_configs')
    op.drop_table('notification_channel_configs')
    op.drop_index(op.f('ix_login_failure_buckets_key'), table_name='login_failure_buckets')
    op.drop_table('login_failure_buckets')
    op.drop_table('holiday_calendars')
    op.drop_index(op.f('ix_ai_usage_ledger_month'), table_name='ai_usage_ledger')
    op.drop_table('ai_usage_ledger')
