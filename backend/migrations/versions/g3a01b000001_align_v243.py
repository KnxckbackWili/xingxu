"""T01: freeze and align the complete 2.4.3 schema; run legacy repairs once.

Revision ID: g3a01b000001
Revises: d2e7f9a103b4
"""
from alembic import op
from sqlalchemy.orm import Session
from migrations.v243_alignment import align_schema

revision = 'g3a01b000001'
down_revision = 'd2e7f9a103b4'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('T01包含存量数据转换，必须在线执行alembic upgrade；拒绝生成会跳过数据转换的离线SQL')
    align_schema(op)
    from migrations import v243_data
    v243_data._is_sqlite = op.get_bind().dialect.name == 'sqlite'
    with Session(bind=op.get_bind(), join_transaction_mode='rollback_only') as db:
        v243_data.migrate_legacy_data(db)
        v243_data.migrate_shared_data(db)
        v243_data.detach_project_phases(db)
        if db.query(v243_data.Phase.id).first():
            v243_data.migrate_scope_preparations(db)
        db.flush()


def downgrade():
    raise RuntimeError('T01 alignment preserves legacy data; restore the verified pre-upgrade backup to downgrade')
