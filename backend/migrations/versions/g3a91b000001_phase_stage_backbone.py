"""Put every work group (phase) on the template stage backbone (document stages 4–9)."""
from alembic import op
import sqlalchemy as sa

revision = 'g3a91b000001'
down_revision = 'g3a90b000001'
branch_labels = None
depends_on = None

# Frozen copy of the name mapping at this revision; later edits to the app constant do not change it.
PHASE_STAGE_BY_NAME = {
    '项目准备': '4', '进场准备': '5',
    '到货检查': '6', '单车调试': '6', '地图与站点': '6', '系统部署': '6',
    '系统联调': '6', '联调工作': '6', '试运行': '6', '试运行工作': '6', '现场追加工作': '6',
    '培训验收': '7',
}


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('主线阶段需要逐条读取工作阶段名称后归类；请在线事务运行')
    op.add_column('phases', sa.Column('stage_key', sa.String(10), nullable=True))
    connection = op.get_bind()
    phases = sa.table('phases', sa.column('id'), sa.column('name'), sa.column('stage_key'))
    for row in connection.execute(sa.select(phases.c.id, phases.c.name)).mappings():
        stage = PHASE_STAGE_BY_NAME.get((row['name'] or '').strip(), '6')
        connection.execute(phases.update().where(phases.c.id == row['id']).values(stage_key=stage))


def downgrade():
    op.drop_column('phases', 'stage_key')
