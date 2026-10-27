"""T30: bind the untouched default-template vehicle work to the H-2 default steps.

Only system default-template rows that still carry their seeded identity, name
and per-vehicle type, and have never been bound, are updated. Generated
projects keep their own definitions; nothing is inferred for project data.
"""
import json
from uuid import uuid4
import sqlalchemy as sa
from alembic import op

revision = 'g3a30b000002'
down_revision = 'g3a40b000002'
branch_labels = None
depends_on = None

# Frozen copy of the seeded mapping at this revision.
SEEDED = {
    'task-005': ('开箱检查', 'arrival_inspection'),
    'task-006': ('配件清点', 'arrival_inspection'),
    'task-007': ('电池与充电器检查', 'arrival_inspection'),
    'task-009': ('单车机械与导航调试', 'single_commissioning'),
    'task-010': ('安全激光及停车距离验证', 'single_commissioning'),
    'task-011': ('单车配置和程序备份', 'single_commissioning'),
    'task-012': ('载荷测试', 'single_commissioning'),
    'task-013': ('异常急停测试', 'single_commissioning'),
    'task-022': ('多车联调', 'system_integration'),
    'task-046': ('自动充电联调', 'system_integration'),
}
DEFAULT_STEP_KEYS = {'arrival_inspection', 'single_commissioning', 'map_stations', 'system_integration', 'go_live'}


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('默认模板车辆环节须在线核对现有模板后补齐，不能以离线DDL跳过')
    bind = op.get_bind()
    customised = [r[0] for r in bind.execute(sa.text("SELECT key FROM vehicle_steps WHERE template_id='default'"))]
    available = set(customised) if customised else DEFAULT_STEP_KEYS
    bound = []
    for task_id, (name, key) in SEEDED.items():
        if key not in available:
            continue
        result = bind.execute(sa.text(
            "UPDATE tasks SET vehicle_step_key=:key WHERE id=:id AND project_id IS NULL AND template_id IS NULL "
            "AND name=:name AND quantity_type='per_vehicle' AND vehicle_step_key IS NULL"),
            {'key': key, 'id': task_id, 'name': name})
        if result.rowcount:
            bound.append({'task_id': task_id, 'vehicle_step_key': key})
    # Seeded presets copied the default tree before it carried step keys. Bind
    # their copies only while the preset was never edited after seeding.
    by_name = {name: key for name, key in SEEDED.values()}
    presets = bind.execute(sa.text(
        "SELECT t.id FROM templates t WHERE t.name IN ('标准 AGV 实施模板','叉车重载项目模板','多车型集成模板') "
        "AND NOT EXISTS (SELECT 1 FROM change_logs c WHERE c.entity_type='template' AND c.entity_id=t.id)")).scalars().all()
    for template_id in presets:
        own = [r[0] for r in bind.execute(sa.text("SELECT key FROM vehicle_steps WHERE template_id=:t"), {'t': template_id})]
        allowed = set(own) if own else DEFAULT_STEP_KEYS
        rows = bind.execute(sa.text(
            "SELECT id,name FROM tasks WHERE template_id=:t AND project_id IS NULL AND quantity_type='per_vehicle' "
            "AND vehicle_step_key IS NULL"), {'t': template_id}).mappings().all()
        for row in rows:
            key = by_name.get(row['name'])
            if key and key in allowed:
                bind.execute(sa.text("UPDATE tasks SET vehicle_step_key=:key WHERE id=:id AND vehicle_step_key IS NULL"),
                             {'key': key, 'id': row['id']})
                bound.append({'task_id': row['id'], 'template_id': template_id, 'vehicle_step_key': key})
    if bound:
        bind.execute(sa.text(
            "INSERT INTO change_logs(id,project_id,entity_type,entity_id,action,operator_id,detail,old_value,new_value,created_at) "
            "VALUES(:id,NULL,'migration',:revision,'bind_vehicle_steps',NULL,:detail,:old,:new,CURRENT_TIMESTAMP)"),
            {'id': str(uuid4()), 'revision': revision,
             'detail': '默认模板未改动的按车辆工作关联默认车辆环节；已生成项目不变',
             'old': json.dumps({'tasks': [{'task_id': row['task_id'], 'vehicle_step_key': None} for row in bound]}),
             'new': json.dumps({'tasks': bound})})


def downgrade():
    raise RuntimeError('不能自动撤回模板环节关联，请恢复一致备份')
