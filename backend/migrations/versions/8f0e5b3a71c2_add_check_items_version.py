"""add check_items.version optimistic lock

Revision ID: 8f0e5b3a71c2
Revises: 870d62543b33
Create Date: 2026-08-25 21:00:00

P2-并发：乐观锁扩展到检查项——现场多端同时打勾不再互相覆盖。
存量库由 _migrate() 的 ensure_column 兜底（无 alembic_version 时 stamp 到 head，
本迁移在已纳入版本管理的库上生效）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8f0e5b3a71c2"
down_revision: Union[str, None] = "870d62543b33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("check_items", sa.Column("version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("check_items", "version")
