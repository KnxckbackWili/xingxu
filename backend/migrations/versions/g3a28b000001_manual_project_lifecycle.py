"""T28: six human-controlled project states; preserve original decisions and audit provenance."""
import json
from uuid import uuid5, NAMESPACE_URL

from alembic import op
import sqlalchemy as sa

revision = 'g3a28b000001'
down_revision = 'g3a30b000001'
branch_labels = None
depends_on = None

STATES = ('preparing', 'ready', 'executing', 'acceptance', 'completed', 'archived', 'suspended')
MAPPED = {'draft': 'preparing', 'planning': 'preparing', 'commissioning': 'executing', 'pilot': 'executing'}


def _json(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _audit_target(row):
    value = _json(row['new_value'])
    if isinstance(value, dict):
        value = value.get('status')
    if value in ('commissioning', 'pilot'):
        return value
    detail = row['detail'] or ''
    if detail.startswith(('项目状态:', '项目状态：')) and '→' in detail:
        return {'系统联调': 'commissioning', '试运行': 'pilot'}.get(detail.rsplit('→', 1)[1].strip())
    return None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('T28 requires the real historical audit rows; run an online transaction, never fabricate an offline data migration')
    op.add_column('projects', sa.Column('legacy_lifecycle', sa.JSON(), nullable=True))
    op.add_column('project_events', sa.Column('actual_date', sa.Date(), nullable=True))
    op.add_column('project_events', sa.Column('actual_source', sa.JSON(), nullable=True))
    connection = op.get_bind()
    projects = sa.table('projects', sa.column('id'), sa.column('status'), sa.column('suspension', sa.JSON()),
                        sa.column('legacy_lifecycle', sa.JSON()), sa.column('version'))
    events = sa.table('project_events', sa.column('id'), sa.column('project_id'), sa.column('event_key'),
                      sa.column('actual_at', sa.DateTime()), sa.column('actual_source', sa.JSON()),
                      sa.column('recorded_by'), sa.column('note'))
    logs = sa.table('change_logs', sa.column('id'), sa.column('project_id'), sa.column('entity_type'),
                    sa.column('action'), sa.column('detail'), sa.column('new_value', sa.JSON()),
                    sa.column('created_at', sa.DateTime()), sa.column('operator_id'))
    users = {row[0] for row in connection.execute(sa.text('SELECT id FROM users'))}
    changed = unknown = restored_events = 0
    for row in connection.execute(sa.select(projects).order_by(projects.c.id)).mappings():
        original = row['status']
        before = _json(row['suspension'])
        target = MAPPED.get(original, original)
        repair = target not in STATES
        context = dict(before) if isinstance(before, dict) else {}
        if original == 'suspended':
            expected = MAPPED.get(context.get('status_before'), context.get('status_before'))
            if expected not in ('preparing', 'ready', 'executing', 'acceptance'):
                repair = True
                context['status_before'] = None
            else:
                context['status_before'] = expected
        if repair:
            target = 'suspended'
            context = {**context, 'status_before': None, 'reason': '历史状态待管理员根据原始记录核对；原值已保留'}
            unknown += 1
        evidence = {'version': 1, 'original_status': original, 'original_suspension': before,
                    'migration': revision, 'requires_repair': repair}
        values = {'status': target, 'legacy_lifecycle': evidence, 'suspension': context}
        if target != original or context != before:
            values['version'] = (row['version'] or 0) + 1
            changed += 1
        connection.execute(projects.update().where(projects.c.id == row['id']).values(**values))
        # A real recorded manual transition is the only timestamp source. Merely
        # being in an old phase is not evidence of a business occurrence time.
        candidates = {}
        for log in connection.execute(sa.select(logs).where(logs.c.project_id == row['id'],
                logs.c.entity_type == 'project', logs.c.action.in_(('status', 'update')))
                .order_by(logs.c.created_at, logs.c.id)).mappings():
            old_target = _audit_target(log)
            if old_target and log['created_at'] is not None:
                candidates[old_target] = log
        for old_target, log in candidates.items():
            key = 'commissioning_done' if old_target == 'commissioning' else 'go_live'
            existing = connection.execute(sa.select(events).where(events.c.project_id == row['id'], events.c.event_key == key)).mappings().first()
            if existing and existing['actual_at'] is not None:
                continue
            source = {'kind': 'legacy_status_transition', 'change_log_id': log['id'],
                      'original_target': old_target, 'time_basis': '原人工状态推进审计时间，非签单所载业务时间'}
            values = {'actual_at': log['created_at'], 'actual_source': source,
                      'recorded_by': log['operator_id'] if log['operator_id'] in users else None}
            if existing:
                connection.execute(events.update().where(events.c.id == existing['id']).values(**values))
            else:
                connection.execute(events.insert().values(id=str(uuid5(NAMESPACE_URL, revision + ':' + row['id'] + ':' + key)),
                    project_id=row['id'], event_key=key, note='由原人工状态推进审计补登；时间依据见来源', **values))
            restored_events += 1
    with op.batch_alter_table('projects') as batch:
        batch.create_check_constraint('ck_project_status', "status IN ('preparing','ready','executing','acceptance','completed','archived','suspended')")
    detail = json.dumps({'changed_projects': changed, 'requires_repair': unknown, 'audit_events_restored': restored_events}, ensure_ascii=False)
    connection.execute(sa.text("INSERT INTO change_logs(id,project_id,entity_type,entity_id,action,operator_id,detail,created_at) VALUES(:id,NULL,'migration',:revision,'lifecycle_migrate',NULL,:detail,CURRENT_TIMESTAMP)"),
                       {'id': 'v3-manual-project-lifecycle-audit', 'revision': revision, 'detail': detail})


def downgrade():
    raise RuntimeError('不能丢弃原状态与签单来源；回退请恢复升级前一致加密备份')
