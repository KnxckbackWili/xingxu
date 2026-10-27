"""T30 vehicle progress, preserving unidentifiable quantity history separately."""
from uuid import uuid4
from math import floor
from alembic import op
import sqlalchemy as sa
import json

revision = 'g3a30b000001'
down_revision = 'g3a27b000001'
branch_labels = None
depends_on = None
DEFAULT_STEPS = [('arrival_inspection','到场点检'), ('single_commissioning','单车调试'),
                 ('map_stations','地图与站点'), ('system_integration','系统联调'), ('go_live','上线运行')]


def upgrade():
    steps = op.create_table('vehicle_steps', sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('template_id',sa.String(36),nullable=False),sa.Column('key',sa.String(80),nullable=False),
        sa.Column('name',sa.String(200),nullable=False),sa.Column('sort_order',sa.Integer(),nullable=False),
        sa.UniqueConstraint('template_id','key',name='uq_vehicle_step_template_key'))
    op.create_index('ix_vehicle_steps_template_id','vehicle_steps',['template_id'])
    project_steps = op.create_table('project_vehicle_steps',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('key',sa.String(80),nullable=False),sa.Column('name',sa.String(300),nullable=False),
        sa.Column('sort_order',sa.Integer(),nullable=False),
        sa.Column('source_task_id',sa.String(36),sa.ForeignKey('tasks.id',ondelete='SET NULL')),
        sa.Column('expected_quantity',sa.Integer()),sa.UniqueConstraint('project_id','key',name='uq_project_vehicle_step_key'))
    op.create_index('ix_project_vehicle_steps_project_id','project_vehicle_steps',['project_id'])
    op.create_table('vehicle_progress',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('vehicle_unit_id',sa.String(36),sa.ForeignKey('vehicle_units.id',ondelete='CASCADE'),nullable=False),
        sa.Column('step_key',sa.String(80),nullable=False),sa.Column('is_done',sa.Boolean(),nullable=False),
        sa.Column('done_on',sa.Date()),sa.Column('recorded_at',sa.DateTime(),nullable=False),
        sa.Column('done_by',sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL')),
        sa.Column('note',sa.Text()),sa.Column('source_metadata',sa.JSON()),sa.Column('migrated',sa.Boolean(),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.UniqueConstraint('vehicle_unit_id','step_key',name='uq_vehicle_progress_unit_step'))
    op.create_index('ix_vehicle_progress_project_id','vehicle_progress',['project_id'])
    op.create_index('ix_vehicle_progress_vehicle_unit_id','vehicle_progress',['vehicle_unit_id'])
    credits = op.create_table('vehicle_progress_migrations',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False),
        sa.Column('step_key',sa.String(80),nullable=False),sa.Column('total_count',sa.Integer(),nullable=False),
        sa.Column('unassigned_count',sa.Integer(),nullable=False),sa.Column('source_metadata',sa.JSON(),nullable=False),
        sa.UniqueConstraint('project_id','step_key',name='uq_vehicle_progress_migration_step'),
        sa.CheckConstraint('unassigned_count >= 0 AND unassigned_count <= total_count',name='ck_vehicle_progress_migration_count'))
    op.create_index('ix_vehicle_progress_migrations_project_id','vehicle_progress_migrations',['project_id'])
    if op.get_context().as_sql:
        raise RuntimeError('T30含历史数量逐条保全，请在线升级，不能以离线DDL绕过数据迁移')
    op.add_column("projects",sa.Column("portable_unverified_snapshot",sa.JSON(),nullable=True))
    op.add_column("vehicle_units",sa.Column("legacy_current_stage",sa.String(80),nullable=True))
    with op.batch_alter_table("vehicle_units") as batch:
        batch.alter_column("current_stage", existing_type=sa.String(30), type_=sa.String(80), existing_nullable=True)
    bind=op.get_bind()
    bind.execute(sa.text("UPDATE vehicle_units SET legacy_current_stage=current_stage,current_stage='planned'"))
    template_ids={'default'} | set(bind.execute(sa.text('SELECT id FROM templates')).scalars())
    for tid in template_ids:
        bind.execute(steps.insert(),[dict(id=str(uuid4()),template_id=tid,key=k,name=n,sort_order=i) for i,(k,n) in enumerate(DEFAULT_STEPS)])
    for project in bind.execute(sa.text('SELECT id, template_id FROM projects')).mappings():
        tasks=bind.execute(sa.text("SELECT t.id,t.name,t.target_quantity,t.manually_completed,t.unit,t.applicable_vehicle_types FROM tasks t JOIN modules m ON m.id=t.module_id JOIN phases p ON p.id=m.phase_id WHERE t.project_id=:pid AND t.quantity_type='per_vehicle' AND p.name != '项目准备' ORDER BY p.sort_order,m.sort_order,t.sort_order,t.id"),{'pid':project['id']}).mappings().all()
        # No old task→new five-step equivalence is known. Keep its exact work name.
        if tasks:
            for i,t in enumerate(tasks):
                target=max(0,floor(t['target_quantity']+0.5)) if t['target_quantity'] is not None and t['target_quantity']>0 else None
                qty=bind.execute(sa.text('SELECT COALESCE(SUM(completed_quantity),0) FROM daily_progress WHERE task_id=:id'),{'id':t['id']}).scalar()
                rounded=max(0,floor(float(qty)+0.5))
                count=target if t['manually_completed'] and target is not None else min(target,rounded) if target is not None else rounded
                key='legacy_'+t['id']
                bind.execute(project_steps.insert().values(id=str(uuid4()),project_id=project['id'],key=key,name='历史环节：'+t['name'],sort_order=i,source_task_id=t['id'],expected_quantity=target))
                bind.execute(credits.insert().values(id=str(uuid4()),project_id=project['id'],step_key=key,total_count=count,unassigned_count=count,
                    source_metadata={'task_id':t['id'],'task_name':t['name'],'target_quantity':t['target_quantity'],'completed_quantity':float(qty),'rounded_target':target,'rounded_completed':count,'quantity_unknown':target is None,'unit':t['unit'],'applicable_vehicle_types':json.loads(t['applicable_vehicle_types']) if isinstance(t['applicable_vehicle_types'],str) else t['applicable_vehicle_types'],'target_rounding_difference':target-float(t['target_quantity']) if target is not None else None,'completion_rounding_difference':count-float(qty),'manually_completed':bool(t['manually_completed']),'identity':'unknown','date':'unknown'}))
        else:
            for i,(k,n) in enumerate(DEFAULT_STEPS):
                bind.execute(project_steps.insert().values(id=str(uuid4()),project_id=project['id'],key=k,name=n,sort_order=i))


def downgrade():
    raise RuntimeError('车辆环节和历史数量凭证不可丢弃；回退请恢复升级前一致备份')
