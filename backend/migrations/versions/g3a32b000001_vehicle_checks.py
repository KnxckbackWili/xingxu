"""T32 per-real-vehicle inspection definitions and facts, legacy qualification untouched."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = 'g3a32b000001'
down_revision = 'g3a24b000001'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('T32须在线逐条保全旧检查定义；不能用离线DDL跳过数据迁移')
    op.add_column('tasks', sa.Column('vehicle_step_key', sa.String(80), nullable=True))
    definitions = op.create_table('vehicle_check_definitions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_check_id', sa.String(36), nullable=False),
        sa.Column('source_version', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(300), nullable=False), sa.Column('description', sa.Text()),
        sa.Column('is_safety_critical', sa.Boolean()), sa.Column('is_required', sa.Boolean()),
        sa.Column('sort_order', sa.Integer()),
        sa.UniqueConstraint('task_id', 'source_check_id', name='uq_vehicle_check_definition_source'))
    for column in ('project_id', 'task_id'):
        op.create_index('ix_vehicle_check_definitions_' + column, 'vehicle_check_definitions', [column])
    with op.batch_alter_table('check_items') as batch:
        batch.add_column(sa.Column('vehicle_unit_id', sa.String(36), nullable=True))
        batch.add_column(sa.Column('vehicle_step_key', sa.String(80), nullable=True))
        batch.add_column(sa.Column('vehicle_check_definition_id', sa.String(36), nullable=True))
        batch.add_column(sa.Column('definition_version', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_check_items_vehicle_unit_id', 'vehicle_units', ['vehicle_unit_id'], ['id'], ondelete='CASCADE')
        batch.create_foreign_key('fk_check_items_vehicle_definition', 'vehicle_check_definitions', ['vehicle_check_definition_id'], ['id'], ondelete='CASCADE')
        batch.create_index('ix_check_items_vehicle_unit_id', ['vehicle_unit_id'])
        batch.create_index('ix_check_items_vehicle_check_definition_id', ['vehicle_check_definition_id'])
        batch.create_unique_constraint('uq_vehicle_check_unit_definition', ['vehicle_unit_id', 'vehicle_check_definition_id'])
    bind = op.get_bind()
    # g30 knows these exact original task IDs. Never infer a default-five match.
    for row in bind.execute(sa.text('SELECT project_id,source_task_id,key FROM project_vehicle_steps WHERE source_task_id IS NOT NULL')).mappings():
        bind.execute(sa.text('UPDATE tasks SET vehicle_step_key=:key WHERE id=:tid AND project_id=:pid'),
                     {'key': row['key'], 'tid': row['source_task_id'], 'pid': row['project_id']})
    rows = bind.execute(sa.text("""SELECT c.*,t.project_id AS owner_project_id FROM check_items c JOIN tasks t ON t.id=c.task_id
        WHERE t.project_id IS NOT NULL AND t.quantity_type='per_vehicle'
        AND (c.project_id=t.project_id OR c.project_id IS NULL)""")).mappings()
    for row in rows:
        bind.execute(definitions.insert().values(id=str(uuid4()), project_id=row['owner_project_id'],
            task_id=row['task_id'], source_check_id=row['id'], source_version=row['version'] or 0, version=1,
            name=row['name'], description=row['description'], is_safety_critical=row['is_safety_critical'],
            is_required=row['is_required'], sort_order=row['sort_order']))
    # Original CheckItem rows/states/actors/timestamps stay task-level. Existing
    # units gain no automatic review obligations and g30 completion is untouched.


def downgrade():
    raise RuntimeError('逐车检查及其来源不可丢弃；回退请恢复升级前一致备份')
