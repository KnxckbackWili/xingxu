"""T41 maintainable complete annual holiday calendars."""
from alembic import op
import sqlalchemy as sa

revision = "g3a41b000001"
down_revision = "g3a22b000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("holiday_calendars",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("holidays", sa.JSON(), nullable=False),
        sa.Column("workdays", sa.JSON(), nullable=False),
        sa.Column("source_name", sa.String(300), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("year >= 1900 AND year <= 2200", name="ck_holiday_calendar_year"))


def downgrade():
    raise RuntimeError("年度日历维护记录不能丢弃；回退请恢复升级前一致备份")
