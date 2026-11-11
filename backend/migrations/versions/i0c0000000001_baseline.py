"""Starting point of the schema (4.0.0): every table as the models define it.

Earlier databases are not upgraded from here; the app moves them aside and starts empty
(app/db.py). Later schema changes are new revisions on top of this one.
"""
import sqlalchemy as sa
from alembic import op

revision = "i0c0000000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('change_logs',
    sa.Column('seq', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('user_name', sa.String(length=100), nullable=False),
    sa.Column('kind', sa.String(length=50), nullable=False),
    sa.Column('row_id', sa.String(length=64), nullable=False),
    sa.Column('row_label', sa.String(length=300), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('field', sa.String(length=50), nullable=False),
    sa.Column('old_value', sa.JSON(), nullable=True),
    sa.Column('new_value', sa.JSON(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('seq')
    )
    op.create_index('ix_change_logs_project_seq', 'change_logs', ['project_id', 'seq'], unique=False)
    op.create_index('ix_change_logs_row', 'change_logs', ['row_id', 'seq'], unique=False)
    op.create_table('login_failures',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('bucket', sa.Integer(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key', 'bucket', name='uq_login_failure')
    )
    op.create_table('projects',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('contract_no', sa.String(length=100), nullable=False),
    sa.Column('customer', sa.String(length=200), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('is_closed', sa.Boolean(), nullable=False),
    sa.Column('rev', sa.Integer(), nullable=False),
    sa.Column('deleted_by', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('templates',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('rev', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('vehicle_types',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('documents',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_project_id'), 'documents', ['project_id'], unique=False)
    op.create_table('files',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('owner_kind', sa.String(length=20), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('mime', sa.String(length=100), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_path', sa.String(length=300), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_files_owner_id'), 'files', ['owner_id'], unique=False)
    op.create_index(op.f('ix_files_project_id'), 'files', ['project_id'], unique=False)
    op.create_table('items',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('spec', sa.String(length=300), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=True),
    sa.Column('unit', sa.String(length=30), nullable=False),
    sa.Column('arrived', sa.Boolean(), nullable=False),
    sa.Column('arrived_by', sa.String(length=36), nullable=True),
    sa.Column('arrived_at', sa.DateTime(), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_items_project_id'), 'items', ['project_id'], unique=False)
    op.create_table('project_steps',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_steps_project_id'), 'project_steps', ['project_id'], unique=False)
    op.create_table('template_rows',
    sa.Column('template_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('spec', sa.String(length=300), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=True),
    sa.Column('unit', sa.String(length=30), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_template_rows_template_id'), 'template_rows', ['template_id'], unique=False)
    op.create_table('vehicles',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_no', sa.String(length=100), nullable=False),
    sa.Column('fleet_no', sa.String(length=50), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('config_no', sa.String(length=100), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicles_project_id'), 'vehicles', ['project_id'], unique=False)
    op.create_table('work_items',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('stage', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('done', sa.Boolean(), nullable=False),
    sa.Column('done_by', sa.String(length=36), nullable=True),
    sa.Column('done_at', sa.DateTime(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_items_project_id'), 'work_items', ['project_id'], unique=False)
    op.create_table('issues',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_id', sa.String(length=36), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('resolution', sa.Text(), nullable=False),
    sa.Column('is_closed', sa.Boolean(), nullable=False),
    sa.Column('closed_by', sa.String(length=36), nullable=True),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_issues_project_id'), 'issues', ['project_id'], unique=False)
    op.create_index(op.f('ix_issues_vehicle_id'), 'issues', ['vehicle_id'], unique=False)
    op.create_table('vehicle_marks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_id', sa.String(length=36), nullable=False),
    sa.Column('step_id', sa.String(length=36), nullable=False),
    sa.Column('done_by', sa.String(length=36), nullable=True),
    sa.Column('done_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['step_id'], ['project_steps.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('vehicle_id', 'step_id', name='uq_vehicle_mark')
    )
    op.create_index(op.f('ix_vehicle_marks_project_id'), 'vehicle_marks', ['project_id'], unique=False)
    op.create_index(op.f('ix_vehicle_marks_step_id'), 'vehicle_marks', ['step_id'], unique=False)
    op.create_index(op.f('ix_vehicle_marks_vehicle_id'), 'vehicle_marks', ['vehicle_id'], unique=False)
    op.create_table('vehicle_records',
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('vehicle_id', sa.String(length=36), nullable=False),
    sa.Column('happened_on', sa.Date(), nullable=True),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('recorded_by_name', sa.String(length=100), nullable=False),
    sa.Column('recorded_on', sa.Date(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicle_records_project_id'), 'vehicle_records', ['project_id'], unique=False)
    op.create_index(op.f('ix_vehicle_records_vehicle_id'), 'vehicle_records', ['vehicle_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_vehicle_records_vehicle_id'), table_name='vehicle_records')
    op.drop_index(op.f('ix_vehicle_records_project_id'), table_name='vehicle_records')
    op.drop_table('vehicle_records')
    op.drop_index(op.f('ix_vehicle_marks_vehicle_id'), table_name='vehicle_marks')
    op.drop_index(op.f('ix_vehicle_marks_step_id'), table_name='vehicle_marks')
    op.drop_index(op.f('ix_vehicle_marks_project_id'), table_name='vehicle_marks')
    op.drop_table('vehicle_marks')
    op.drop_index(op.f('ix_issues_vehicle_id'), table_name='issues')
    op.drop_index(op.f('ix_issues_project_id'), table_name='issues')
    op.drop_table('issues')
    op.drop_index(op.f('ix_work_items_project_id'), table_name='work_items')
    op.drop_table('work_items')
    op.drop_index(op.f('ix_vehicles_project_id'), table_name='vehicles')
    op.drop_table('vehicles')
    op.drop_index(op.f('ix_template_rows_template_id'), table_name='template_rows')
    op.drop_table('template_rows')
    op.drop_index(op.f('ix_project_steps_project_id'), table_name='project_steps')
    op.drop_table('project_steps')
    op.drop_index(op.f('ix_items_project_id'), table_name='items')
    op.drop_table('items')
    op.drop_index(op.f('ix_files_project_id'), table_name='files')
    op.drop_index(op.f('ix_files_owner_id'), table_name='files')
    op.drop_table('files')
    op.drop_index(op.f('ix_documents_project_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_table('vehicle_types')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_table('templates')
    op.drop_table('projects')
    op.drop_table('login_failures')
    op.drop_index('ix_change_logs_row', table_name='change_logs')
    op.drop_index('ix_change_logs_project_seq', table_name='change_logs')
    op.drop_table('change_logs')
