"""add unique (project_id, client_uuid) on issues

Revision ID: e5a2f7c9d104
Revises: c9f2d1a4b0e3
Create Date: 2026-09-04 10:00:00

HYPE-99：问题台账跨项目约束 —— (project_id, client_uuid) 库级唯一，杜绝并发
离线上报/导入产生重复台账。

- 存量重复不静默删除：若已存在重复非空 (project_id, client_uuid)，迁移直接报错
  并给出定位信息，由管理员人工合并后重试，绝不自动删业务数据。
- 新库由 create_all（模型 __table_args__ 的 UniqueConstraint）直接建约束；
  存量库在此补唯一索引。SQLite/PG 的唯一索引对 NULL client_uuid 天然放行
  （NULL 互不相等），不影响普通（非离线）上报。
- SQLite 无 alembic_version 的存量库由 _migrate() 的 IF NOT EXISTS 兜底补索引。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5a2f7c9d104"
down_revision: Union[str, None] = "c9f2d1a4b0e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _duplicate_rows() -> list:
    """返回重复的非空 (project_id, client_uuid) 分组（用于报错定位，不删除）。"""
    return op.get_bind().execute(sa.text(
        "SELECT project_id, client_uuid, COUNT(*) AS c FROM issues "
        "WHERE client_uuid IS NOT NULL "
        "GROUP BY project_id, client_uuid HAVING COUNT(*) > 1"
    )).fetchall()


def upgrade() -> None:
    # alembic 离线渲染（sql=True）不能执行任意 SQL → 只在真实连接上查重复。
    ctx = op.get_context()
    if not getattr(ctx, "as_sql", False):
        dups = _duplicate_rows()
        if dups:
            sample = dups[0]
            raise RuntimeError(
                "issues 表存在重复的 (project_id, client_uuid)：project_id=%s, "
                "client_uuid=%s（重复 %s 行）。为不静默删除业务数据，唯一索引迁移中止；"
                "请人工合并重复台账后重跑迁移。" % (sample[0], sample[1], sample[2])
            )
    op.create_index(
        "uq_issue_project_client_uuid", "issues",
        ["project_id", "client_uuid"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_issue_project_client_uuid", table_name="issues")
