"""add projects.timezone

Revision ID: c9f2d1a4b0e3
Revises: 8f0e5b3a71c2
Create Date: 2026-08-25 21:30:00

P2-体验：项目级时区（俄/越现场）——按项目现场时区取"当地今天"，避免海外
现场与服务器(默认上海)日历日相差一天导致"今日任务/撤回窗口"错位。
存量库由 _migrate() 的 ensure_column 兜底（无 alembic_version 时 stamp 到 head）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9f2d1a4b0e3"
down_revision: Union[str, None] = "8f0e5b3a71c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("timezone", sa.String(length=64), nullable=True))
    # 存量行回填默认时区；新行由模型 default 写入
    op.execute("UPDATE projects SET timezone = 'Asia/Shanghai' WHERE timezone IS NULL")


def downgrade() -> None:
    op.drop_column("projects", "timezone")
