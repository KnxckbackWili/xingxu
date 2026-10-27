"""Weekly plans retain every original daily entry and its publication state."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
import math
import json
import sqlalchemy as sa
from alembic import op
from migrations.v3_weekly_intent import summarize

revision = 'g3a40b000001'
down_revision = 'g3a34b000001'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('T40须在线按周完整保全原日程与发布事实，不能以离线DDL跳过')
    table = op.create_table('weekly_plan_cells',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope_key', sa.String(160), nullable=False),
        sa.Column('scope', sa.JSON(), nullable=False),
        sa.Column('vehicle_step_key', sa.String(80), nullable=True),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('mode', sa.String(20), nullable=False),
        sa.Column('target_count', sa.Integer(), nullable=True),
        sa.Column('assignee_ids', sa.JSON(), nullable=False),
        sa.Column('published', sa.Boolean(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('published_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_cancelled', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('source_metadata', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('project_id', 'task_id', 'scope_key', 'week_start', name='uq_weekly_plan_work_scope_week'),
        sa.CheckConstraint("mode IN ('finish','in_progress')", name='ck_weekly_plan_mode'),
        sa.CheckConstraint('target_count IS NULL OR target_count > 0', name='ck_weekly_plan_positive_target'))
    for name in ('project_id', 'task_id', 'week_start'):
        op.create_index('ix_weekly_plan_cells_' + name, 'weekly_plan_cells', [name])
    bind = op.get_bind()
    tasks = {r['id']: dict(r) for r in bind.execute(sa.text('SELECT id,project_id,quantity_type,vehicle_step_key FROM tasks')).mappings()}
    groups = defaultdict(list)
    for record in bind.execute(sa.text('SELECT * FROM schedule_entries ORDER BY project_id,task_id,work_date,id')).mappings():
        row = dict(record)
        day = row['work_date'] if isinstance(row['work_date'], date) else date.fromisoformat(row['work_date'])
        monday = day - timedelta(days=day.weekday())
        groups[(row['project_id'], row['task_id'], monday, bool(row['is_confirmed']), row['status'] == 'skipped')].append(row)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    def plain(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, float) and not math.isfinite(value):
            return {'invalid_original_number': str(value)}
        return value
    project_cells=defaultdict(list)
    for (pid, tid, monday, published, cancelled), rows in groups.items():
        task = tasks.get(tid)
        if task is None or task['project_id'] != pid:
            # Broken foreign ownership is still preserved in its immutable source
            # and cannot become an executable plan for a different project.
            raise RuntimeError('原日程工作归属不一致，请先从备份核对；未创建猜测周计划')
        summary = summarize(rows, task['quantity_type'] == 'per_vehicle')
        source = {
            'kind': 't40_legacy_daily_rollup',
            'original_entries': [{key: plain(value) for key, value in r.items()} for r in rows],
            'original_entry_ids': [r['id'] for r in rows],
            **{key: value for key, value in summary.items() if key not in ('mode', 'target_count')},
            'publication_time': 'unknown', 'publication_actor': 'unknown',
        }
        cell_id=str(uuid4())
        project_cells[pid].append(cell_id)
        bind.execute(table.insert().values(id=cell_id, project_id=pid, task_id=tid,
            scope_key=f"all:legacy:{'published' if published else 'draft'}:{'cancelled' if cancelled else 'active'}",
            scope={'vehicle_unit_ids': []}, vehicle_step_key=task['vehicle_step_key'], week_start=monday,
            mode=summary['mode'], target_count=summary['target_count'],
            assignee_ids=sorted({r['assignee_id'] for r in rows if r['assignee_id']}),
            published=published, published_at=None, published_by=None, is_cancelled=cancelled,
            notes='历史按日日程按周汇总；原日期、负责人、计划量与发布状态只读保全',
            source_metadata=source, created_by=None, created_at=now, updated_by=None, updated_at=now, version=0))

    for pid,ids in project_cells.items():
        bind.execute(sa.text("INSERT INTO change_logs (id,project_id,entity_type,entity_id,action,detail,old_value,new_value,created_at) VALUES (:id,:pid,'weekly_plan',:pid,'migrate_weeks',:detail,:old,:new,:at)"),
            {'id':str(uuid4()),'pid':pid,'detail':f'原按日日程按周保全汇总为 {len(ids)} 格；原行、负责人和发布状态不变，未推定实际执行或发布时间',
             'old':json.dumps({'source':'schedule_entries','unchanged':True}),'new':json.dumps({'cell_ids':ids,'source_kind':'t40_legacy_daily_rollup'}),'at':now})


def downgrade():
    raise RuntimeError('周计划和原日程来源不可丢弃，回退请恢复一致备份')
