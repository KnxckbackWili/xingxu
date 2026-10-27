"""Stage → work item; retain original hierarchy, quantities and execution facts."""
from uuid import uuid4
from datetime import datetime,timezone
import json
from alembic import op
import sqlalchemy as sa
revision='g3a34b000001'
down_revision='g3a53b000001'
branch_labels=None
depends_on=None


def upgrade():
    if op.get_context().as_sql:raise RuntimeError('T34须在线逐条保全工作来源和完成事实，不能以离线DDL跳过')
    with op.batch_alter_table('tasks') as batch:
        batch.add_column(sa.Column('phase_id',sa.String(36),nullable=True))
        batch.add_column(sa.Column('group_label',sa.String(200),nullable=True))
        batch.add_column(sa.Column('scope_conditions',sa.JSON(),nullable=True))
        batch.add_column(sa.Column('legacy_work_snapshot',sa.JSON(),nullable=True))
        batch.create_foreign_key('fk_tasks_phase_id','phases',['phase_id'],['id'],ondelete='SET NULL')
        batch.create_index('ix_tasks_phase_id',['phase_id'])
        batch.alter_column('module_id',existing_type=sa.String(36),existing_nullable=False,nullable=True)
    bind=op.get_bind()
    tasks=sa.table('tasks',sa.column('id',sa.String()),sa.column('phase_id',sa.String()),sa.column('group_label',sa.String()),
        sa.column('scope_conditions',sa.JSON()),sa.column('legacy_work_snapshot',sa.JSON()),sa.column('manually_completed',sa.Boolean()),
        sa.column('manual_completed_by',sa.String()),sa.column('manual_completed_at',sa.DateTime()),sa.column('manual_completed_role',sa.String()),sa.column('manual_completed_reason',sa.Text()))
    phase_table=sa.table('phases',sa.column('id',sa.String()),sa.column('project_id',sa.String()),sa.column('template_id',sa.String()),
        sa.column('name',sa.String()),sa.column('sort_order',sa.Integer()),sa.column('color',sa.String()),sa.column('entry_criteria',sa.Text()),sa.column('exit_criteria',sa.Text()))
    phases={p['id']:dict(p) for p in bind.execute(sa.text('SELECT * FROM phases')).mappings()}
    modules={m['id']:dict(m) for m in bind.execute(sa.text('SELECT * FROM modules')).mappings()}
    copies={}
    def parsed(value,default):
        return json.loads(value) if isinstance(value,str) else value if value is not None else default
    def plain(value):
        return value.isoformat() if hasattr(value,'isoformat') else value
    for t in bind.execute(sa.text('SELECT * FROM tasks ORDER BY id')).mappings().all():
        module=modules.get(t['module_id']) or {};phase=phases.get(module.get('phase_id')) or {}
        pid=t['project_id'];phase_id=phase.get('id')
        if not phase_id or pid and phase.get('project_id')!=pid:
            key=(pid,None if pid else t['template_id'],phase_id)
            if key not in copies:
                copies[key]=str(uuid4())
                bind.execute(phase_table.insert().values(id=copies[key],project_id=pid,template_id=t['template_id'] if not pid else None,
                    name=phase.get('name') or '历史未分类',sort_order=phase.get('sort_order') or 0,color=phase.get('color') or '#1890ff',
                    entry_criteria=phase.get('entry_criteria') or '',exit_criteria=phase.get('exit_criteria') or ''))
            phase_id=copies[key]
        reports=bind.execute(sa.text('SELECT completed_quantity FROM daily_progress WHERE task_id=:tid'),{'tid':t['id']}).scalars().all()
        quantity=sum(float(q or 0) for q in reports)
        source={'kind':'t34_legacy_work','task':{k:plain(t[k]) for k in ('id','name','description','quantity_type','target_quantity','unit','standard_hours','sort_order','safety_flag','source_task_id','source_vehicle_event_id','manually_completed','manual_completed_by','manual_completed_role','manual_completed_at','manual_completed_reason')},
            'module':{k:plain(module.get(k)) for k in ('id','name','category','phase_id','source_module_id')},
            'phase':{k:plain(phase.get(k)) for k in ('id','name','project_id')},'completed_quantity':quantity,'report_count':len(reports),'scope_conditions':parsed(module.get('preparation_conditions'),[])}
        for field in ('depends_on','applicable_vehicle_types','manual_check_overrides'):
            source['task'][field]=parsed(t[field],None)
        values={'phase_id':phase_id,'group_label':module.get('name') or '',
            'scope_conditions':parsed(module.get('preparation_conditions'),[]),'legacy_work_snapshot':source}
        # Conserve old effective completion. Never infer a named actor or time
        # from a sum of reports, nor convert incomplete quality into completion.
        if pid and phase.get('name')!='项目准备' and t['quantity_type']!='per_vehicle' and not t['manually_completed']:
            checks=bind.execute(sa.text('SELECT * FROM check_items WHERE task_id=:tid'),{'tid':t['id']}).mappings().all()
            quality=any((c['is_safety_critical'] and (not c['is_done'] or c['failed'] or not c['is_applicable'])) or
                (c['is_applicable'] and (c['failed'] or c['is_required'] and not c['is_done'])) for c in checks)
            all_na=bool(checks) and not any(c['is_applicable'] for c in checks)
            complete=not quality and (all_na or t['target_quantity'] is not None and t['target_quantity']>0 and quantity>=t['target_quantity']-1e-9)
            if complete:
                reason='迁移：原检查全部不适用' if all_na else '迁移：原报工达到原目标且质量条件满足'
                values.update(manually_completed=True,manual_completed_by=None,manual_completed_role=None,manual_completed_at=None,manual_completed_reason=reason)
                bind.execute(sa.text("INSERT INTO change_logs (id,project_id,entity_type,entity_id,action,detail,old_value,new_value,created_at) VALUES (:id,:pid,'task',:tid,'migrate_work',:detail,:old,:new,:at)"),
                    {'id':str(uuid4()),'pid':pid,'tid':t['id'],'detail':reason,'old':json.dumps({'manually_completed':False}),
                     'new':json.dumps({'manually_completed':True,'basis':'legacy_verified_quantity','identity':'unknown','date':'unknown'}),'at':datetime.now(timezone.utc).replace(tzinfo=None)})
        bind.execute(tasks.update().where(tasks.c.id==t['id']).values(**values))


def downgrade():raise RuntimeError('工作项原事实和迁移来源不可丢弃，回退须恢复一致备份')
