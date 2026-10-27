"""T20 milestone dates, dispatch platform and per-vehicle arrival dates."""
from datetime import date
import json
import uuid

from alembic import op
import sqlalchemy as sa

revision = "g3a20b000001"
down_revision = "g3a03b000001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError("T20旧日期转换需要在线读取并核对，不能离线跳过")
    op.add_column("projects", sa.Column("dispatch_platform", sa.String(20), nullable=True))
    op.add_column("vehicle_units", sa.Column("arrived_at", sa.Date(), nullable=True))
    events = op.create_table("project_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.String(32), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("actual_at", sa.DateTime(), nullable=True),
        sa.Column("recorded_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("project_id", "event_key", name="uq_project_event_key"),
        sa.CheckConstraint("event_key IN ('internal_kickoff','ship','arrival_all','delivery_signed','commissioning_done','go_live','training_done','acceptance','handover')", name="ck_project_event_key"))
    op.create_index("ix_project_events_project_id", "project_events", ["project_id"])
    projects = sa.table("projects", sa.column("id"), sa.column("planned_entry_date", sa.Date()), sa.column("entry_plan", sa.JSON()))
    for project_id, ship_date, entry_plan in op.get_bind().execute(sa.select(projects)):
        if isinstance(entry_plan, str):
            entry_plan = json.loads(entry_plan)
        if entry_plan is not None and not isinstance(entry_plan, dict):
            raise RuntimeError(f"项目{project_id}旧入场安排不是有效对象；请先核对，迁移不猜测日期")
        raw_arrival = (entry_plan or {}).get("entry_date")
        try:
            arrival = date.fromisoformat(raw_arrival) if raw_arrival else None
        except (ValueError, TypeError):
            raise RuntimeError(f"项目{project_id}旧入场计划日期无效；请先核对原始日期，迁移不猜测") from None
        for key, value in (("ship", ship_date), ("arrival_all", arrival)):
            if value:
                op.get_bind().execute(events.insert().values(id=str(uuid.uuid4()), project_id=project_id,
                    event_key=key, planned_date=value, actual_at=None, recorded_by=None,
                    note="由旧计划日期迁移，未推定实际发生时间"))


def downgrade():
    raise RuntimeError("T20新增关键事件和到场资料不能丢弃；回退请恢复升级前一致备份")
