"""Frozen 2.4.3 schema. Historical migrations must not import live models."""
import uuid
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.orm import registry

def gen_uuid():
    return str(uuid.uuid4())

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

metadata = sa.MetaData()

sa.Table('ai_jobs', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False, default='generic'),
    sa.Column('status', sa.String(length=20), nullable=False, default='queued'),
    sa.Column('percent', sa.Integer(), nullable=False, default=2),
    sa.Column('stage', sa.String(length=40), nullable=False, default='queued'),
    sa.Column('message', sa.Text(), nullable=False, default=''),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
)
sa.Index('ix_ai_jobs_user_id', metadata.tables['ai_jobs'].c['user_id'], unique=False)

sa.Table('ai_rate_limit_buckets', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('bucket', sa.Integer(), nullable=False),
    sa.Column('window', sa.Integer(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False, default=0),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.UniqueConstraint('user_id', 'scope', 'bucket', 'window', name='uq_ai_rate_limit_user_scope_bucket_window'),
)
sa.Index('ix_ai_rate_limit_buckets_user_id', metadata.tables['ai_rate_limit_buckets'].c['user_id'], unique=False)

sa.Table('ai_usage_ledger', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('month', sa.String(length=7), nullable=False),
    sa.Column('requests', sa.Integer(), nullable=True, default=0),
    sa.Column('tokens', sa.Integer(), nullable=True, default=0),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.UniqueConstraint('month', name='uq_ai_usage_month'),
)
sa.Index('ix_ai_usage_ledger_month', metadata.tables['ai_usage_ledger'].c['month'], unique=False)

sa.Table('login_failure_buckets', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('bucket', sa.Integer(), nullable=False),
    sa.Column('window', sa.Integer(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False, default=0),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.UniqueConstraint('key', 'bucket', 'window', name='uq_login_failure_key_bucket_window'),
)
sa.Index('ix_login_failure_buckets_key', metadata.tables['login_failure_buckets'].c['key'], unique=False)

sa.Table('notification_channel_configs', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('channel', sa.String(length=30), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False, default=False),
    sa.Column('webhook_url_encrypted', sa.Text(), nullable=True, default=''),
    sa.Column('secret_encrypted', sa.Text(), nullable=True, default=''),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('last_test_at', sa.DateTime(), nullable=True),
    sa.Column('last_test_success', sa.Boolean(), nullable=True),
    sa.Column('last_test_detail', sa.String(length=300), nullable=True, default=''),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
)
sa.Index('ix_notification_channel_configs_channel', metadata.tables['notification_channel_configs'].c['channel'], unique=True)

sa.Table('notification_outbox', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('notification_id', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('content', sa.Text(), nullable=True, default=''),
    sa.Column('ntype', sa.String(length=30), nullable=True, default='system'),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=True, default='pending'),
    sa.Column('attempts', sa.Integer(), nullable=True, default=0),
    sa.Column('max_attempts', sa.Integer(), nullable=True, default=3),
    sa.Column('next_retry_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True, default=''),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
)
sa.Index('ix_notification_outbox_idempotency_key', metadata.tables['notification_outbox'].c['idempotency_key'], unique=True)
sa.Index('ix_notification_outbox_next_retry_at', metadata.tables['notification_outbox'].c['next_retry_at'], unique=False)
sa.Index('ix_notification_outbox_status', metadata.tables['notification_outbox'].c['status'], unique=False)

sa.Table('offline_op_receipts', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('op_type', sa.String(length=20), nullable=False),
    sa.Column('client_uuid', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.UniqueConstraint('user_id', 'op_type', 'project_id', 'client_uuid', name='uq_offline_op_receipt_user_op_uuid'),
)
sa.Index('ix_offline_op_receipts_user_id', metadata.tables['offline_op_receipts'].c['user_id'], unique=False)

sa.Table('org_groups', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('leader_id', sa.String(length=36), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
)

sa.Table('project_archives', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('project_name', sa.String(length=200), nullable=True, default=''),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('change_logs', sa.JSON(), nullable=False),
    sa.Column('actor_ids', sa.JSON(), nullable=True, default=list),
    sa.Column('checksum', sa.String(length=64), nullable=False),
    sa.Column('purged_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
)
sa.Index('ix_project_archives_project_id', metadata.tables['project_archives'].c['project_id'], unique=False)

sa.Table('project_creation_receipts', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('client_uuid', sa.String(length=64), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.UniqueConstraint('user_id', 'client_uuid', name='uq_project_creation_user_uuid'),
)

sa.Table('rate_limit_buckets', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('bucket', sa.Integer(), nullable=False),
    sa.Column('window', sa.Integer(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False, default=0),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.UniqueConstraint('user_id', 'bucket', 'window', name='uq_rate_limit_user_bucket_window'),
)
sa.Index('ix_rate_limit_buckets_user_id', metadata.tables['rate_limit_buckets'].c['user_id'], unique=False)

sa.Table('scheduler_watermarks', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('job_id', sa.String(length=50), nullable=False),
    sa.Column('last_success_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=20), nullable=True, default='ok'),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.UniqueConstraint('job_id', name=None),
)

sa.Table('template_docs', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('stored_name', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=True, default=0),
    sa.Column('content_type', sa.String(length=100), nullable=True, default=''),
    sa.Column('note', sa.String(length=300), nullable=True, default=''),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True, default=utcnow),
)
sa.Index('ix_template_docs_task_id', metadata.tables['template_docs'].c['task_id'], unique=False)

sa.Table('template_preparation_items', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=True, default='scope'),
    sa.Column('is_required', sa.Boolean(), nullable=True, default=True),
    sa.Column('blocks_entry', sa.Boolean(), nullable=True, default=False),
    sa.Column('owner_party', sa.String(length=20), nullable=True, default='project'),
    sa.Column('risk', sa.String(length=10), nullable=True, default='low'),
    sa.Column('condition', sa.String(length=20), nullable=True, default='default'),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
)

sa.Table('template_procurement_items', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=True, default='件'),
    sa.Column('spec', sa.String(length=300), nullable=True, default=''),
    sa.Column('due_weeks', sa.Integer(), nullable=True, default=0),
    sa.Column('condition', sa.String(length=20), nullable=True, default='default'),
    sa.Column('is_required', sa.Boolean(), nullable=True, default=True),
    sa.Column('owner_party', sa.String(length=20), nullable=True, default='procurement'),
    sa.Column('risk', sa.String(length=10), nullable=True, default='low'),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
)

sa.Table('templates', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('is_system', sa.Boolean(), nullable=True, default=False),
    sa.Column('version', sa.Integer(), nullable=True, default=1),
    sa.Column('status', sa.String(length=10), nullable=True, default='draft'),
    sa.Column('snapshots', sa.JSON(), nullable=True, default=list),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
)

sa.Table('users', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False, default='worker'),
    sa.Column('group_id', sa.String(length=36), nullable=True),
    sa.Column('phone', sa.String(length=20), nullable=True, default=''),
    sa.Column('email', sa.String(length=100), nullable=True, default=''),
    sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
    sa.Column('token_version', sa.Integer(), nullable=True, default=0),
    sa.Column('permission_overrides', sa.JSON(), nullable=True, default=dict),
    sa.Column('permission_version', sa.Integer(), nullable=False, server_default='0', default=0),
    sa.Column('skills', sa.JSON(), nullable=True, default=list),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
)
sa.Index('ix_users_username', metadata.tables['users'].c['username'], unique=True)

sa.Table('vehicle_types', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False, default=True),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
)
sa.Index('ix_vehicle_types_name', metadata.tables['vehicle_types'].c['name'], unique=True)

sa.Table('ai_api_tokens', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('token_prefix', sa.String(length=16), nullable=True, default=''),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=True, default=list),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None, name=None),
)
sa.Index('ix_ai_api_tokens_token_hash', metadata.tables['ai_api_tokens'].c['token_hash'], unique=True)
sa.Index('ix_ai_api_tokens_user_id', metadata.tables['ai_api_tokens'].c['user_id'], unique=False)

sa.Table('ai_chat_sessions', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=True, default=''),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_ai_chat_sessions_user_id', metadata.tables['ai_chat_sessions'].c['user_id'], unique=False)

sa.Table('ai_user_memories', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('content', sa.String(length=1000), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=True, default='manual'),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_ai_user_memories_user_id', metadata.tables['ai_user_memories'].c['user_id'], unique=False)

sa.Table('feedback', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('steps', sa.Text(), nullable=False, default=''),
    sa.Column('status', sa.String(length=20), nullable=False, default='pending'),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None, name=None),
)
sa.Index('ix_feedback_status', metadata.tables['feedback'].c['status'], unique=False)
sa.Index('ix_feedback_user_id', metadata.tables['feedback'].c['user_id'], unique=False)

sa.Table('inbox_documents', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('stored_name', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=True, default=0),
    sa.Column('content_type', sa.String(length=100), nullable=True, default=''),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('status', sa.String(length=20), nullable=True, default='pending'),
    sa.Column('extracted_text', sa.Text(), nullable=True, default=''),
    sa.Column('ai_result', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True, default=''),
    sa.Column('organized_at', sa.DateTime(), nullable=True),
    sa.Column('archived_project_id', sa.String(length=36), nullable=True),
    sa.Column('archived_attachment_id', sa.String(length=36), nullable=True),
    sa.Column('archived_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete=None, name=None),
)

sa.Table('notifications', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('content', sa.Text(), nullable=True, default=''),
    sa.Column('ntype', sa.String(length=30), nullable=True, default='system'),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('entity_id', sa.String(length=36), nullable=True),
    sa.Column('is_read', sa.Boolean(), nullable=True, default=False),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_notifications_user_id', metadata.tables['notifications'].c['user_id'], unique=False)

sa.Table('project_governance_requests', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('project_name', sa.String(length=200), nullable=True, default=''),
    sa.Column('request_type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=True, default='pending'),
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('target_manager_id', sa.String(length=36), nullable=True),
    sa.Column('source_manager_id', sa.String(length=36), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('review_note', sa.Text(), nullable=True, default=''),
    sa.Column('reviewed_by', sa.String(length=36), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['target_manager_id'], ['users.id'], ondelete=None, name=None),
)
sa.Index('ix_project_governance_requests_project_id', metadata.tables['project_governance_requests'].c['project_id'], unique=False)

sa.Table('projects', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('abbreviation', sa.String(length=50), nullable=True, default=''),
    sa.Column('manager', sa.String(length=100), nullable=True, default=''),
    sa.Column('technical_manager', sa.String(length=36), nullable=True),
    sa.Column('co_managers', sa.JSON(), nullable=True, default=list),
    sa.Column('is_demo', sa.Boolean(), nullable=True, default=False),
    sa.Column('client', sa.String(length=200), nullable=True, default=''),
    sa.Column('location', sa.String(length=200), nullable=True, default=''),
    sa.Column('timezone', sa.String(length=64), nullable=True, default='Asia/Shanghai'),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False, default='draft'),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('staffing_notes', sa.Text(), nullable=True, default=''),
    sa.Column('members', sa.JSON(), nullable=True, default=list),
    sa.Column('member_permissions', sa.JSON(), nullable=True, default=list),
    sa.Column('role_plan', sa.JSON(), nullable=True, default=dict),
    sa.Column('rest_mode', sa.String(length=10), nullable=True, default='none'),
    sa.Column('rest_days', sa.JSON(), nullable=True, default=list),
    sa.Column('skip_holidays', sa.Boolean(), nullable=True, default=False),
    sa.Column('schedule_version', sa.Integer(), nullable=True, default=0),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('template_version', sa.Integer(), nullable=True, default=0),
    sa.Column('planned_entry_date', sa.Date(), nullable=True),
    sa.Column('readiness_state', sa.String(length=20), nullable=True, default='preparing'),
    sa.Column('prep_conditions', sa.JSON(), nullable=True, default=list),
    sa.Column('prep_confirmed_by', sa.String(length=36), nullable=True),
    sa.Column('prep_confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('prep_conclusion', sa.Text(), nullable=True, default=''),
    sa.Column('client_contacts', sa.JSON(), nullable=True, default=list),
    sa.Column('entry_plan', sa.JSON(), nullable=True, default=dict),
    sa.Column('suspension', sa.JSON(), nullable=True, default=dict),
    sa.Column('retrospective', sa.JSON(), nullable=True, default=dict),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True, default=0),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete=None, name=None),
)

sa.Table('team_templates', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=300), nullable=True, default=''),
    sa.Column('roles', sa.JSON(), nullable=True, default=dict),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete=None, name=None),
)

sa.Table('user_unavailability', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('reason', sa.String(length=100), nullable=True, default='其他'),
    sa.Column('note', sa.Text(), nullable=True, default=''),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_user_unavailability_user_id', metadata.tables['user_unavailability'].c['user_id'], unique=False)

sa.Table('acceptance_records', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('accepted_by', sa.String(length=36), nullable=True),
    sa.Column('accepted_by_name', sa.String(length=100), nullable=True, default=''),
    sa.Column('accepted_at', sa.Date(), nullable=False),
    sa.Column('scope_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('conclusion', sa.String(length=30), nullable=True, default='accepted'),
    sa.Column('notes', sa.Text(), nullable=True, default=''),
    sa.Column('attachment_id', sa.String(length=36), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['accepted_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_acceptance_records_project_id', metadata.tables['acceptance_records'].c['project_id'], unique=False)

sa.Table('ai_chat_messages', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['session_id'], ['ai_chat_sessions.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_ai_chat_messages_session_id', metadata.tables['ai_chat_messages'].c['session_id'], unique=False)

sa.Table('archive_checklists', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=False),
    sa.Column('item_name', sa.String(length=200), nullable=False),
    sa.Column('is_required', sa.Boolean(), nullable=True, default=True),
    sa.Column('is_done', sa.Boolean(), nullable=True, default=False),
    sa.Column('done_by', sa.String(length=36), nullable=True),
    sa.Column('done_at', sa.DateTime(), nullable=True),
    sa.Column('attachment_id', sa.String(length=36), nullable=True),
    sa.Column('requirements', sa.JSON(), nullable=True, default=dict),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_archive_checklists_project_id', metadata.tables['archive_checklists'].c['project_id'], unique=False)

sa.Table('attachments', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('entity_type', sa.String(length=50), nullable=True, default='project'),
    sa.Column('entity_id', sa.String(length=36), nullable=True, default=''),
    sa.Column('category', sa.String(length=50), nullable=True, default=''),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('stored_name', sa.String(length=100), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=True, default=0),
    sa.Column('content_type', sa.String(length=100), nullable=True, default=''),
    sa.Column('uploaded_by', sa.String(length=36), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete=None, name=None),
)
sa.Index('ix_attachments_project_id', metadata.tables['attachments'].c['project_id'], unique=False)

sa.Table('change_logs', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('entity_type', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('operator_id', sa.String(length=36), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True, default=''),
    sa.Column('old_value', sa.JSON(), nullable=True),
    sa.Column('new_value', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_change_logs_project_id', metadata.tables['change_logs'].c['project_id'], unique=False)

sa.Table('incidents', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False, default=''),
    sa.Column('incident_type', sa.String(length=20), nullable=False, default='other'),
    sa.Column('severity', sa.String(length=20), nullable=False, default='medium'),
    sa.Column('status', sa.String(length=20), nullable=False, default='open'),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('occurred_at', sa.DateTime(), nullable=False),
    sa.Column('reporter_id', sa.String(length=36), nullable=False),
    sa.Column('impact', sa.JSON(), nullable=True, default=dict),
    sa.Column('blocked_task_ids', sa.JSON(), nullable=True, default=list),
    sa.Column('mitigation', sa.Text(), nullable=True, default=''),
    sa.Column('retrospective', sa.Text(), nullable=True, default=''),
    sa.Column('mitigated_at', sa.DateTime(), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete=None, name=None),
)
sa.Index('ix_incidents_project_id', metadata.tables['incidents'].c['project_id'], unique=False)

sa.Table('item_applications', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=True, default=''),
    sa.Column('item_name', sa.String(length=200), nullable=True, default=''),
    sa.Column('requirement', sa.Text(), nullable=True, default=''),
    sa.Column('reason', sa.Text(), nullable=True, default=''),
    sa.Column('drawing_no', sa.String(length=100), nullable=True, default=''),
    sa.Column('contract_no', sa.String(length=100), nullable=True, default=''),
    sa.Column('amount', sa.String(length=100), nullable=True, default=''),
    sa.Column('applicant', sa.String(length=100), nullable=True, default=''),
    sa.Column('approver', sa.String(length=100), nullable=True, default=''),
    sa.Column('department', sa.String(length=100), nullable=True, default=''),
    sa.Column('apply_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True, default='pending'),
    sa.Column('note', sa.Text(), nullable=True, default=''),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_item_applications_project_id', metadata.tables['item_applications'].c['project_id'], unique=False)

sa.Table('personal_events', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('notes', sa.String(length=500), nullable=True, default=''),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None, name=None),
)
sa.Index('ix_personal_events_project_id', metadata.tables['personal_events'].c['project_id'], unique=False)
sa.Index('ix_personal_events_user_id', metadata.tables['personal_events'].c['user_id'], unique=False)
sa.Index('ix_personal_events_work_date', metadata.tables['personal_events'].c['work_date'], unique=False)

sa.Table('phases', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.Column('color', sa.String(length=20), nullable=True, default='#1890ff'),
    sa.Column('entry_criteria', sa.Text(), nullable=True, default=''),
    sa.Column('exit_criteria', sa.Text(), nullable=True, default=''),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_phases_project_id', metadata.tables['phases'].c['project_id'], unique=False)
sa.Index('ix_phases_template_id', metadata.tables['phases'].c['template_id'], unique=False)

sa.Table('project_change_sets', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('baseline_version', sa.Integer(), nullable=False, default=0),
    sa.Column('baseline_data', sa.JSON(), nullable=True),
    sa.Column('changes', sa.JSON(), nullable=False),
    sa.Column('reverse_data', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False, default='draft'),
    sa.Column('merged_by', sa.String(length=36), nullable=True),
    sa.Column('merged_at', sa.DateTime(), nullable=True),
    sa.Column('merged_version', sa.Integer(), nullable=True),
    sa.Column('rolled_back_by', sa.String(length=36), nullable=True),
    sa.Column('rolled_back_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_project_change_sets_project_id', metadata.tables['project_change_sets'].c['project_id'], unique=False)

sa.Table('project_deletion_records', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('deleted_by', sa.String(length=36), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=False),
    sa.Column('status_before_delete', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False, default=''),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('backup_name', sa.String(length=100), nullable=False),
    sa.Column('backup_sha256', sa.String(length=64), nullable=False),
    sa.Column('backup_bytes', sa.Integer(), nullable=False),
    sa.Column('protected_from_purge', sa.Boolean(), nullable=False, default=True),
    sa.Column('restored_by', sa.String(length=36), nullable=True),
    sa.Column('restored_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['deleted_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['restored_by'], ['users.id'], ondelete=None, name=None),
)
sa.Index('ix_project_deletion_records_deleted_at', metadata.tables['project_deletion_records'].c['deleted_at'], unique=False)
sa.Index('ix_project_deletion_records_project_id', metadata.tables['project_deletion_records'].c['project_id'], unique=False)

sa.Table('project_edit_history', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('actor_id', sa.String(length=36), nullable=False),
    sa.Column('chain_id', sa.String(length=36), nullable=False),
    sa.Column('save_version', sa.Integer(), nullable=False),
    sa.Column('guard_version', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False, default='applied'),
    sa.Column('before_data', sa.JSON(), nullable=False),
    sa.Column('after_data', sa.JSON(), nullable=False),
    sa.Column('blocked_reason', sa.Text(), nullable=False, default=''),
    sa.Column('created_at', sa.DateTime(), nullable=False, default=utcnow),
    sa.Column('last_action_at', sa.DateTime(), nullable=True),
    sa.Column('last_action_version', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.UniqueConstraint('project_id', 'save_version', name='uq_project_edit_save_version'),
)
sa.Index('ix_project_edit_history_actor_id', metadata.tables['project_edit_history'].c['actor_id'], unique=False)
sa.Index('ix_project_edit_history_chain_id', metadata.tables['project_edit_history'].c['chain_id'], unique=False)
sa.Index('ix_project_edit_history_project_id', metadata.tables['project_edit_history'].c['project_id'], unique=False)

sa.Table('project_inventory_items', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('item_code', sa.String(length=100), nullable=True, default=''),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=True, default='other'),
    sa.Column('ownership', sa.String(length=20), nullable=False, default='company'),
    sa.Column('tracking_mode', sa.String(length=20), nullable=True, default='quantity'),
    sa.Column('specification', sa.String(length=300), nullable=True, default=''),
    sa.Column('serial_number', sa.String(length=200), nullable=True, default=''),
    sa.Column('quantity', sa.Float(), nullable=False, default=0),
    sa.Column('minimum_quantity', sa.Float(), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=True, default='件'),
    sa.Column('status', sa.String(length=30), nullable=True, default='on_site'),
    sa.Column('location', sa.String(length=200), nullable=True, default=''),
    sa.Column('custodian', sa.String(length=100), nullable=True, default=''),
    sa.Column('supplier', sa.String(length=200), nullable=True, default=''),
    sa.Column('received_date', sa.Date(), nullable=True),
    sa.Column('expected_return_date', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True, default=''),
    sa.Column('extra', sa.JSON(), nullable=True, default=dict),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_project_inventory_items_item_code', metadata.tables['project_inventory_items'].c['item_code'], unique=False)
sa.Index('ix_project_inventory_items_name', metadata.tables['project_inventory_items'].c['name'], unique=False)
sa.Index('ix_project_inventory_items_project_id', metadata.tables['project_inventory_items'].c['project_id'], unique=False)

sa.Table('project_members', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=True, default='member'),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name=None),
    sa.UniqueConstraint('project_id', 'user_id', name='uq_project_member'),
)
sa.Index('ix_project_members_project_id', metadata.tables['project_members'].c['project_id'], unique=False)
sa.Index('ix_project_members_user_id', metadata.tables['project_members'].c['user_id'], unique=False)

sa.Table('project_preparation_items', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False, default='scope'),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=True),
    sa.Column('is_required', sa.Boolean(), nullable=True, default=True),
    sa.Column('blocks_entry', sa.Boolean(), nullable=True, default=False),
    sa.Column('status', sa.String(length=20), nullable=True, default='not_started'),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.Column('owner_party', sa.String(length=20), nullable=True, default='project'),
    sa.Column('required_date', sa.Date(), nullable=True),
    sa.Column('committed_date', sa.Date(), nullable=True),
    sa.Column('forecast_date', sa.Date(), nullable=True),
    sa.Column('planned_date', sa.Date(), nullable=True),
    sa.Column('actual_date', sa.Date(), nullable=True),
    sa.Column('risk', sa.String(length=10), nullable=True, default='low'),
    sa.Column('affected_phase_id', sa.String(length=36), nullable=True),
    sa.Column('affected_task_id', sa.String(length=36), nullable=True),
    sa.Column('completed_by', sa.String(length=36), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True, default=''),
    sa.Column('extra', sa.JSON(), nullable=True, default=dict),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_project_preparation_items_project_id', metadata.tables['project_preparation_items'].c['project_id'], unique=False)

sa.Table('project_readiness_reviews', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('conclusion', sa.String(length=20), nullable=False),
    sa.Column('reviewer_id', sa.String(length=36), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('notes', sa.Text(), nullable=True, default=''),
    sa.Column('remaining_risks', sa.JSON(), nullable=True, default=list),
    sa.Column('snapshot', sa.JSON(), nullable=True, default=list),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_project_readiness_reviews_project_id', metadata.tables['project_readiness_reviews'].c['project_id'], unique=False)

sa.Table('project_schedule_policies', metadata,
    sa.Column('project_id', sa.String(length=36), nullable=False, primary_key=True),
    sa.Column('duration_scale', sa.Float(), nullable=False, default=1),
    sa.Column('version', sa.Integer(), nullable=False, default=0),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)

sa.Table('vehicles', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_type', sa.String(length=50), nullable=False),
    sa.Column('model_name', sa.String(length=100), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False, default=1),
    sa.Column('configuration', sa.JSON(), nullable=True, default=dict),
    sa.Column('notes', sa.Text(), nullable=True, default=''),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_vehicles_project_id', metadata.tables['vehicles'].c['project_id'], unique=False)

sa.Table('incident_actions', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('incident_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('action_type', sa.String(length=30), nullable=False, default='note'),
    sa.Column('operator_id', sa.String(length=36), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True, default=''),
    sa.Column('extra', sa.JSON(), nullable=True, default=dict),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_incident_actions_incident_id', metadata.tables['incident_actions'].c['incident_id'], unique=False)
sa.Index('ix_incident_actions_project_id', metadata.tables['incident_actions'].c['project_id'], unique=False)

sa.Table('modules', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('source_module_id', sa.String(length=36), nullable=True),
    sa.Column('phase_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=True, default='core'),
    sa.Column('is_selected', sa.Boolean(), nullable=True, default=True),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('preparation_conditions', sa.JSON(), nullable=True, default=list),
    sa.Column('applies_to_all_vehicles', sa.Boolean(), nullable=True, default=True),
    sa.ForeignKeyConstraint(['phase_id'], ['phases.id'], ondelete='SET NULL', name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_modules_project_id', metadata.tables['modules'].c['project_id'], unique=False)
sa.Index('ix_modules_source_module_id', metadata.tables['modules'].c['source_module_id'], unique=False)
sa.Index('ix_modules_template_id', metadata.tables['modules'].c['template_id'], unique=False)

sa.Table('project_inventory_movements', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('item_id', sa.String(length=36), nullable=False),
    sa.Column('movement_type', sa.String(length=30), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False, default=0),
    sa.Column('balance_after', sa.Float(), nullable=False, default=0),
    sa.Column('from_location', sa.String(length=200), nullable=True, default=''),
    sa.Column('to_location', sa.String(length=200), nullable=True, default=''),
    sa.Column('handler', sa.String(length=100), nullable=True, default=''),
    sa.Column('occurred_at', sa.DateTime(), nullable=False, default=utcnow),
    sa.Column('time_basis', sa.String(length=20), nullable=True, default='utc'),
    sa.Column('note', sa.Text(), nullable=True, default=''),
    sa.Column('operator_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['item_id'], ['project_inventory_items.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_project_inventory_movements_item_id', metadata.tables['project_inventory_movements'].c['item_id'], unique=False)
sa.Index('ix_project_inventory_movements_project_id', metadata.tables['project_inventory_movements'].c['project_id'], unique=False)

sa.Table('vehicle_units', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_id', sa.String(length=36), nullable=True),
    sa.Column('asset_code', sa.String(length=100), nullable=False),
    sa.Column('serial_number', sa.String(length=100), nullable=True, default=''),
    sa.Column('fleet_no', sa.String(length=30), nullable=True, default=''),
    sa.Column('model_name', sa.String(length=100), nullable=True, default=''),
    sa.Column('current_stage', sa.String(length=30), nullable=True, default='planned'),
    sa.Column('current_status', sa.String(length=30), nullable=True, default='normal'),
    sa.Column('location', sa.String(length=200), nullable=True, default=''),
    sa.Column('warranty_end', sa.Date(), nullable=True),
    sa.Column('commissioned_at', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True, default=''),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL', name=None),
    sa.UniqueConstraint('project_id', 'asset_code', name='uq_vehicle_unit_asset'),
)
sa.Index('ix_vehicle_units_project_id', metadata.tables['vehicle_units'].c['project_id'], unique=False)
sa.Index('ix_vehicle_units_vehicle_id', metadata.tables['vehicle_units'].c['vehicle_id'], unique=False)

sa.Table('vehicle_lifecycle_events', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('vehicle_unit_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('event_type', sa.String(length=30), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('fault_part', sa.String(length=200), nullable=True, default=''),
    sa.Column('cause', sa.Text(), nullable=True, default=''),
    sa.Column('action_taken', sa.Text(), nullable=True, default=''),
    sa.Column('replaced_parts', sa.JSON(), nullable=True, default=list),
    sa.Column('downtime_hours', sa.Float(), nullable=True),
    sa.Column('verification', sa.Text(), nullable=True, default=''),
    sa.Column('handler', sa.String(length=100), nullable=True, default=''),
    sa.Column('is_closed', sa.Boolean(), nullable=True, default=False),
    sa.Column('stage_after', sa.String(length=30), nullable=True, default=''),
    sa.Column('status_after', sa.String(length=30), nullable=True, default=''),
    sa.Column('location_after', sa.String(length=200), nullable=True, default=''),
    sa.Column('attachment_id', sa.String(length=36), nullable=True),
    sa.Column('operator_id', sa.String(length=36), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=True, default=dict),
    sa.Column('import_key', sa.String(length=64), nullable=True, default=''),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('updated_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['vehicle_unit_id'], ['vehicle_units.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_vehicle_lifecycle_events_import_key', metadata.tables['vehicle_lifecycle_events'].c['import_key'], unique=False)
sa.Index('ix_vehicle_lifecycle_events_project_id', metadata.tables['vehicle_lifecycle_events'].c['project_id'], unique=False)
sa.Index('ix_vehicle_lifecycle_events_vehicle_unit_id', metadata.tables['vehicle_lifecycle_events'].c['vehicle_unit_id'], unique=False)

sa.Table('tasks', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('module_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('quantity_type', sa.String(length=20), nullable=False, default='per_vehicle'),
    sa.Column('target_quantity', sa.Float(), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=True, default='台'),
    sa.Column('standard_hours', sa.Float(), nullable=True),
    sa.Column('safety_flag', sa.Boolean(), nullable=True, default=False),
    sa.Column('applicable_vehicle_types', sa.JSON(), nullable=True, default=list),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.Column('depends_on', sa.JSON(), nullable=True, default=list),
    sa.Column('deliverables', sa.JSON(), nullable=True, default=list),
    sa.Column('reference_docs', sa.JSON(), nullable=True, default=list),
    sa.Column('version', sa.Integer(), nullable=True, default=0),
    sa.Column('source_task_id', sa.String(length=36), nullable=True),
    sa.Column('source_vehicle_event_id', sa.String(length=36), nullable=True),
    sa.Column('manually_completed', sa.Boolean(), nullable=True, default=False),
    sa.Column('manual_completed_by', sa.String(length=36), nullable=True),
    sa.Column('manual_completed_role', sa.String(length=20), nullable=True),
    sa.Column('manual_completed_at', sa.DateTime(), nullable=True),
    sa.Column('manual_completed_reason', sa.Text(), nullable=True, default=''),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['source_vehicle_event_id'], ['vehicle_lifecycle_events.id'], ondelete='SET NULL', name=None),
    sa.UniqueConstraint('source_vehicle_event_id', name=None),
)
sa.Index('ix_tasks_module_id', metadata.tables['tasks'].c['module_id'], unique=False)
sa.Index('ix_tasks_project_id', metadata.tables['tasks'].c['project_id'], unique=False)
sa.Index('ix_tasks_source_task_id', metadata.tables['tasks'].c['source_task_id'], unique=False)
sa.Index('ix_tasks_template_id', metadata.tables['tasks'].c['template_id'], unique=False)

sa.Table('check_items', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=36), nullable=True),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('is_safety_critical', sa.Boolean(), nullable=True, default=False),
    sa.Column('is_required', sa.Boolean(), nullable=True, default=True),
    sa.Column('is_applicable', sa.Boolean(), nullable=True, default=True),
    sa.Column('not_applicable_reason', sa.Text(), nullable=True, default=''),
    sa.Column('not_applicable_set_by', sa.String(length=36), nullable=True),
    sa.Column('not_applicable_set_at', sa.DateTime(), nullable=True),
    sa.Column('is_done', sa.Boolean(), nullable=True, default=False),
    sa.Column('done_by', sa.String(length=36), nullable=True),
    sa.Column('done_at', sa.DateTime(), nullable=True),
    sa.Column('failed', sa.Boolean(), nullable=True, default=False),
    sa.Column('failed_reason', sa.Text(), nullable=True, default=''),
    sa.Column('sort_order', sa.Integer(), nullable=True, default=0),
    sa.Column('version', sa.Integer(), nullable=True, default=0),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_check_items_project_id', metadata.tables['check_items'].c['project_id'], unique=False)
sa.Index('ix_check_items_task_id', metadata.tables['check_items'].c['task_id'], unique=False)
sa.Index('ix_check_items_template_id', metadata.tables['check_items'].c['template_id'], unique=False)

sa.Table('issues', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True, default=''),
    sa.Column('issue_type', sa.String(length=20), nullable=True, default='other'),
    sa.Column('severity', sa.String(length=20), nullable=True, default='medium'),
    sa.Column('status', sa.String(length=20), nullable=True, default='open'),
    sa.Column('reporter_id', sa.String(length=36), nullable=False),
    sa.Column('assignee_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolution', sa.Text(), nullable=True, default=''),
    sa.Column('extra', sa.JSON(), nullable=True, default=dict),
    sa.Column('version', sa.Integer(), nullable=True, default=0),
    sa.Column('client_uuid', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL', name=None),
    sa.UniqueConstraint('project_id', 'client_uuid', name='uq_issue_project_client_uuid'),
)
sa.Index('ix_issues_project_id', metadata.tables['issues'].c['project_id'], unique=False)

sa.Table('schedule_entries', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('assignee_id', sa.String(length=36), nullable=True),
    sa.Column('planned_quantity', sa.Float(), nullable=True, default=0),
    sa.Column('status', sa.String(length=20), nullable=True, default='planned'),
    sa.Column('notes', sa.Text(), nullable=True, default=''),
    sa.Column('is_confirmed', sa.Boolean(), nullable=True, default=False),
    sa.Column('is_locked', sa.Boolean(), nullable=True, default=False),
    sa.Column('version', sa.Integer(), nullable=True, default=0),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete=None, name=None),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_schedule_entries_project_id', metadata.tables['schedule_entries'].c['project_id'], unique=False)
sa.Index('ix_schedule_entries_task_id', metadata.tables['schedule_entries'].c['task_id'], unique=False)

sa.Table('task_duration_overrides', metadata,
    sa.Column('task_id', sa.String(length=36), nullable=False, primary_key=True),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('workdays', sa.Integer(), nullable=False, default=1),
    sa.Column('baseline_quantity', sa.Float(), nullable=False, default=1),
    sa.Column('baseline_unit', sa.String(length=20), nullable=False, default='项'),
    sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
    sa.Column('recovered_from_log_id', sa.String(length=36), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False, default=0),
    sa.Column('updated_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE', name=None),
)
sa.Index('ix_task_duration_overrides_project_id', metadata.tables['task_duration_overrides'].c['project_id'], unique=False)

sa.Table('daily_progress', metadata,
    sa.Column('id', sa.String(length=36), nullable=False, primary_key=True, default=gen_uuid),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('schedule_entry_id', sa.String(length=36), nullable=True),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('completed_quantity', sa.Float(), nullable=True, default=0),
    sa.Column('note', sa.Text(), nullable=True, default=''),
    sa.Column('client_uuid', sa.String(length=36), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=True, default='worker'),
    sa.Column('created_at', sa.DateTime(), nullable=True, default=utcnow),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['schedule_entry_id'], ['schedule_entries.id'], ondelete='SET NULL', name=None),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE', name=None),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete=None, name=None),
    sa.UniqueConstraint('task_id', 'work_date', 'user_id', 'client_uuid', name='uq_progress_dedupe'),
)
sa.Index('ix_daily_progress_project_id', metadata.tables['daily_progress'].c['project_id'], unique=False)
sa.Index('ix_daily_progress_task_id', metadata.tables['daily_progress'].c['task_id'], unique=False)

mapper_registry = registry(metadata=metadata)

AcceptanceRecord = type('AcceptanceRecord', (), {})
mapper_registry.map_imperatively(AcceptanceRecord, metadata.tables['acceptance_records'])
AiApiToken = type('AiApiToken', (), {})
mapper_registry.map_imperatively(AiApiToken, metadata.tables['ai_api_tokens'])
AiChatMessage = type('AiChatMessage', (), {})
mapper_registry.map_imperatively(AiChatMessage, metadata.tables['ai_chat_messages'])
AiChatSession = type('AiChatSession', (), {})
mapper_registry.map_imperatively(AiChatSession, metadata.tables['ai_chat_sessions'])
AiJob = type('AiJob', (), {})
mapper_registry.map_imperatively(AiJob, metadata.tables['ai_jobs'])
AiRateLimitBucket = type('AiRateLimitBucket', (), {})
mapper_registry.map_imperatively(AiRateLimitBucket, metadata.tables['ai_rate_limit_buckets'])
AiUsageLedger = type('AiUsageLedger', (), {})
mapper_registry.map_imperatively(AiUsageLedger, metadata.tables['ai_usage_ledger'])
AiUserMemory = type('AiUserMemory', (), {})
mapper_registry.map_imperatively(AiUserMemory, metadata.tables['ai_user_memories'])
ArchiveChecklist = type('ArchiveChecklist', (), {})
mapper_registry.map_imperatively(ArchiveChecklist, metadata.tables['archive_checklists'])
Attachment = type('Attachment', (), {})
mapper_registry.map_imperatively(Attachment, metadata.tables['attachments'])
ChangeLog = type('ChangeLog', (), {})
mapper_registry.map_imperatively(ChangeLog, metadata.tables['change_logs'])
CheckItem = type('CheckItem', (), {})
mapper_registry.map_imperatively(CheckItem, metadata.tables['check_items'])
DailyProgress = type('DailyProgress', (), {})
mapper_registry.map_imperatively(DailyProgress, metadata.tables['daily_progress'])
Feedback = type('Feedback', (), {})
mapper_registry.map_imperatively(Feedback, metadata.tables['feedback'])
InboxDocument = type('InboxDocument', (), {})
mapper_registry.map_imperatively(InboxDocument, metadata.tables['inbox_documents'])
Incident = type('Incident', (), {})
mapper_registry.map_imperatively(Incident, metadata.tables['incidents'])
IncidentAction = type('IncidentAction', (), {})
mapper_registry.map_imperatively(IncidentAction, metadata.tables['incident_actions'])
Issue = type('Issue', (), {})
mapper_registry.map_imperatively(Issue, metadata.tables['issues'])
ItemApplication = type('ItemApplication', (), {})
mapper_registry.map_imperatively(ItemApplication, metadata.tables['item_applications'])
LoginFailureBucket = type('LoginFailureBucket', (), {})
mapper_registry.map_imperatively(LoginFailureBucket, metadata.tables['login_failure_buckets'])
Module = type('Module', (), {})
mapper_registry.map_imperatively(Module, metadata.tables['modules'])
Notification = type('Notification', (), {})
mapper_registry.map_imperatively(Notification, metadata.tables['notifications'])
NotificationChannelConfig = type('NotificationChannelConfig', (), {})
mapper_registry.map_imperatively(NotificationChannelConfig, metadata.tables['notification_channel_configs'])
NotificationOutbox = type('NotificationOutbox', (), {})
mapper_registry.map_imperatively(NotificationOutbox, metadata.tables['notification_outbox'])
OfflineOpReceipt = type('OfflineOpReceipt', (), {})
mapper_registry.map_imperatively(OfflineOpReceipt, metadata.tables['offline_op_receipts'])
OrgGroup = type('OrgGroup', (), {})
mapper_registry.map_imperatively(OrgGroup, metadata.tables['org_groups'])
PersonalEvent = type('PersonalEvent', (), {})
mapper_registry.map_imperatively(PersonalEvent, metadata.tables['personal_events'])
Phase = type('Phase', (), {})
mapper_registry.map_imperatively(Phase, metadata.tables['phases'])
Project = type('Project', (), {})
mapper_registry.map_imperatively(Project, metadata.tables['projects'])
ProjectArchive = type('ProjectArchive', (), {})
mapper_registry.map_imperatively(ProjectArchive, metadata.tables['project_archives'])
ProjectChangeSet = type('ProjectChangeSet', (), {})
mapper_registry.map_imperatively(ProjectChangeSet, metadata.tables['project_change_sets'])
ProjectCreationReceipt = type('ProjectCreationReceipt', (), {})
mapper_registry.map_imperatively(ProjectCreationReceipt, metadata.tables['project_creation_receipts'])
ProjectDeletionRecord = type('ProjectDeletionRecord', (), {})
mapper_registry.map_imperatively(ProjectDeletionRecord, metadata.tables['project_deletion_records'])
ProjectEditHistory = type('ProjectEditHistory', (), {})
mapper_registry.map_imperatively(ProjectEditHistory, metadata.tables['project_edit_history'])
ProjectGovernanceRequest = type('ProjectGovernanceRequest', (), {})
mapper_registry.map_imperatively(ProjectGovernanceRequest, metadata.tables['project_governance_requests'])
ProjectInventoryItem = type('ProjectInventoryItem', (), {})
mapper_registry.map_imperatively(ProjectInventoryItem, metadata.tables['project_inventory_items'])
ProjectInventoryMovement = type('ProjectInventoryMovement', (), {})
mapper_registry.map_imperatively(ProjectInventoryMovement, metadata.tables['project_inventory_movements'])
ProjectMember = type('ProjectMember', (), {})
mapper_registry.map_imperatively(ProjectMember, metadata.tables['project_members'])
ProjectPreparationItem = type('ProjectPreparationItem', (), {})
mapper_registry.map_imperatively(ProjectPreparationItem, metadata.tables['project_preparation_items'])
ProjectReadinessReview = type('ProjectReadinessReview', (), {})
mapper_registry.map_imperatively(ProjectReadinessReview, metadata.tables['project_readiness_reviews'])
ProjectSchedulePolicy = type('ProjectSchedulePolicy', (), {})
mapper_registry.map_imperatively(ProjectSchedulePolicy, metadata.tables['project_schedule_policies'])
RateLimitBucket = type('RateLimitBucket', (), {})
mapper_registry.map_imperatively(RateLimitBucket, metadata.tables['rate_limit_buckets'])
ScheduleEntry = type('ScheduleEntry', (), {})
mapper_registry.map_imperatively(ScheduleEntry, metadata.tables['schedule_entries'])
SchedulerWatermark = type('SchedulerWatermark', (), {})
mapper_registry.map_imperatively(SchedulerWatermark, metadata.tables['scheduler_watermarks'])
Task = type('Task', (), {})
mapper_registry.map_imperatively(Task, metadata.tables['tasks'])
TaskDurationOverride = type('TaskDurationOverride', (), {})
mapper_registry.map_imperatively(TaskDurationOverride, metadata.tables['task_duration_overrides'])
TeamTemplate = type('TeamTemplate', (), {})
mapper_registry.map_imperatively(TeamTemplate, metadata.tables['team_templates'])
Template = type('Template', (), {})
mapper_registry.map_imperatively(Template, metadata.tables['templates'])
TemplateDoc = type('TemplateDoc', (), {})
mapper_registry.map_imperatively(TemplateDoc, metadata.tables['template_docs'])
TemplatePreparationItem = type('TemplatePreparationItem', (), {})
mapper_registry.map_imperatively(TemplatePreparationItem, metadata.tables['template_preparation_items'])
TemplateProcurementItem = type('TemplateProcurementItem', (), {})
mapper_registry.map_imperatively(TemplateProcurementItem, metadata.tables['template_procurement_items'])
User = type('User', (), {})
mapper_registry.map_imperatively(User, metadata.tables['users'])
UserUnavailability = type('UserUnavailability', (), {})
mapper_registry.map_imperatively(UserUnavailability, metadata.tables['user_unavailability'])
Vehicle = type('Vehicle', (), {})
mapper_registry.map_imperatively(Vehicle, metadata.tables['vehicles'])
VehicleLifecycleEvent = type('VehicleLifecycleEvent', (), {})
mapper_registry.map_imperatively(VehicleLifecycleEvent, metadata.tables['vehicle_lifecycle_events'])
VehicleType = type('VehicleType', (), {})
mapper_registry.map_imperatively(VehicleType, metadata.tables['vehicle_types'])
VehicleUnit = type('VehicleUnit', (), {})
mapper_registry.map_imperatively(VehicleUnit, metadata.tables['vehicle_units'])
