"""Merge the former ready stage into preparing; keep each project's original status as provenance."""
import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = 'g3a90b000001'
down_revision = 'g3a30b000002'
branch_labels = None
depends_on = None

STATES = ('preparing', 'executing', 'acceptance', 'completed', 'archived', 'suspended')


def _json(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('阶段合并需要逐个读取项目原状态并留痕；请在线事务运行，不能用离线 SQL 代替数据迁移')
    connection = op.get_bind()
    projects = sa.table('projects', sa.column('id'), sa.column('status'), sa.column('suspension', sa.JSON()),
                        sa.column('legacy_lifecycle', sa.JSON()), sa.column('version'))
    logs = sa.table('change_logs', sa.column('id'), sa.column('project_id'), sa.column('entity_type'),
                    sa.column('entity_id'), sa.column('action'), sa.column('operator_id'), sa.column('detail'),
                    sa.column('old_value', sa.JSON()), sa.column('new_value', sa.JSON()), sa.column('created_at', sa.DateTime()))
    changed = []
    for row in connection.execute(sa.select(projects).order_by(projects.c.id)).mappings():
        suspension = _json(row['suspension'])
        suspension = dict(suspension) if isinstance(suspension, dict) else {}
        status = row['status']
        if status != 'ready' and not (status == 'suspended' and suspension.get('status_before') == 'ready'):
            continue
        evidence = _json(row['legacy_lifecycle'])
        evidence = dict(evidence) if isinstance(evidence, dict) else {}
        evidence['ready_merge'] = {'migration': revision, 'original_status': status,
                                   'original_status_before': suspension.get('status_before')}
        values = {'legacy_lifecycle': evidence, 'version': (row['version'] or 0) + 1}
        if status == 'ready':
            values['status'] = 'preparing'
            detail = '阶段合并：待进场 → 准备（原状态已保留）'
        else:
            values['suspension'] = {**suspension, 'status_before': 'preparing'}
            detail = '阶段合并：停工前状态 待进场 → 准备（原状态已保留）'
        connection.execute(projects.update().where(projects.c.id == row['id']).values(**values))
        connection.execute(logs.insert().values(
            id=str(uuid5(NAMESPACE_URL, f'{revision}:{row["id"]}')),
            project_id=row['id'], entity_type='project', entity_id=row['id'], action='update', operator_id=None,
            detail=detail, old_value={'status': status, 'status_before': suspension.get('status_before')},
            new_value={'status': values.get('status', status), 'status_before': values.get('suspension', suspension).get('status_before')},
            created_at=sa.func.current_timestamp()))
        changed.append(row['id'])
    with op.batch_alter_table('projects') as batch:
        batch.drop_constraint('ck_project_status', type_='check')
        batch.create_check_constraint('ck_project_status', "status IN ('preparing','executing','acceptance','completed','archived','suspended')")
    connection.execute(sa.text("INSERT INTO change_logs(id,project_id,entity_type,entity_id,action,operator_id,detail,created_at) VALUES(:id,NULL,'migration',:revision,'lifecycle_migrate',NULL,:detail,CURRENT_TIMESTAMP)"),
                       {'id': 'v3-merge-ready-into-preparing', 'revision': revision,
                        'detail': json.dumps({'changed_projects': len(changed)}, ensure_ascii=False)})


def downgrade():
    raise RuntimeError('阶段合并保留了原状态来源；回退请恢复升级前一致加密备份')
