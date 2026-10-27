"""T40: unknown legacy quantities require explicit current planning review."""
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4
import json
import sqlalchemy as sa
from alembic import op
from migrations.v3_weekly_intent import summarize

revision = 'g3a40b000002'
down_revision = 'g3a33b000001'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('T40计划未知量须在线逐来源核对，不能以离线DDL跳过')
    op.add_column('weekly_plan_cells', sa.Column('intent_review_required', sa.Boolean(), nullable=True))
    bind = op.get_bind()
    table = sa.table('weekly_plan_cells', sa.column('id', sa.String()),
        sa.column('mode', sa.String()), sa.column('target_count', sa.Integer()),
        sa.column('source_metadata', sa.JSON()), sa.column('intent_review_required', sa.Boolean()),
        sa.column('version', sa.Integer()))
    tasks = {r['id']: r['quantity_type'] for r in bind.execute(sa.text('SELECT id,quantity_type FROM tasks')).mappings()}
    audits = defaultdict(list)
    for row in bind.execute(sa.text('SELECT * FROM weekly_plan_cells ORDER BY id')).mappings():
        source = json.loads(row['source_metadata']) if isinstance(row['source_metadata'],str) else row['source_metadata']
        values = {'intent_review_required': False}
        if isinstance(source,dict) and source.get('kind') == 't40_legacy_daily_rollup':
            originals = source.get('original_entries')
            if not isinstance(originals,list) or not originals or any(not isinstance(r,dict) or 'planned_quantity' not in r for r in originals):
                raise RuntimeError('原周计划量来源缺失，拒绝猜测核对状态')
            summary = summarize(originals,tasks[row['task_id']] == 'per_vehicle')
            refreshed = {**source, **{key:value for key,value in summary.items() if key not in ('mode','target_count')}}
            values.update(source_metadata=refreshed, intent_review_required=summary['migration_review_required'])
            # A previously-applied, unreleased g40 may have treated NULL as zero.
            # Correct only those unknown definitions, retaining every original row
            # and recording the previous current plan in the system audit.
            if summary['unknown_quantity_count']:
                values.update(mode='finish', target_count=None)
                if row['mode'] != 'finish' or row['target_count'] is not None:
                    values['version'] = (row['version'] or 0) + 1
            if values['intent_review_required']:
                audits[row['project_id']].append({'id':row['id'],'previous_mode':row['mode'],
                    'previous_target_count':row['target_count'],'previous_version':row['version'] or 0,
                    'unknown_quantity_count':summary['unknown_quantity_count']})
        bind.execute(table.update().where(table.c.id == row['id']).values(**values))
    with op.batch_alter_table('weekly_plan_cells') as batch:
        batch.alter_column('intent_review_required',existing_type=sa.Boolean(),nullable=False)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for pid,cells in audits.items():
        bind.execute(sa.text("INSERT INTO change_logs (id,project_id,entity_type,entity_id,action,detail,old_value,new_value,created_at) VALUES (:id,:pid,'weekly_plan',:pid,'review_plan_intent',:detail,:old,:new,:at)"),
            {'id':str(uuid4()),'pid':pid,'detail':'原计划未知量或不能确定的车辆目标需明确核对；原来源、实际完成与负责人不变',
             'old':json.dumps({'cells':cells}),'new':json.dumps({'cell_ids':[c['id'] for c in cells],'intent_review_required':True}),'at':now})


def downgrade():
    raise RuntimeError('不能丢弃未知计划量核对状态，请恢复一致备份')
