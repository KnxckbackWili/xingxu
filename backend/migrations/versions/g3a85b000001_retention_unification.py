"""#85: durable encrypted-backup receipts and preserve legacy recycled projects."""
from alembic import op
import sqlalchemy as sa

revision = 'g3a85b000001'
down_revision = 'g3a41b000001'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite INTEGER already stores signed 64-bit values; PostgreSQL INTEGER
    # needs widening before project archives can exceed two GiB.
    if op.get_context().dialect.name == 'postgresql':
        op.alter_column('project_deletion_records', 'backup_bytes', existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)
    op.create_table('project_permanent_backups',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('project_name', sa.String(200), nullable=False),
        sa.Column('deletion_id', sa.String(36), nullable=False),
        sa.Column('project_version', sa.Integer(), nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('backup_name', sa.String(100), nullable=False),
        sa.Column('backup_sha256', sa.String(64), nullable=False),
        sa.Column('backup_bytes', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('prepared_by', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('prepared_at', sa.DateTime(), nullable=False),
        sa.Column('purged_by', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('purged_at', sa.DateTime()))
    op.create_index('ix_project_permanent_backups_project_id', 'project_permanent_backups', ['project_id'])
    # Static SQL: preserve rows/timestamps, do not read files or require backup
    # credentials at startup. A UUID project id is a valid stable legacy cycle id.
    op.execute("""INSERT INTO project_deletion_records
        (id,project_id,deleted_by,deleted_at,status_before_delete,reason,snapshot,
         backup_name,backup_sha256,backup_bytes,protected_from_purge)
        SELECT p.id,p.id,NULL,p.deleted_at,COALESCE(p.status,'legacy_unknown'),'历史软删除项目统一纳入回收站',
               '{}','','',0,TRUE FROM projects p
        WHERE p.deleted_at IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM project_deletion_records r WHERE r.project_id=p.id
             AND r.deleted_at=p.deleted_at AND r.restored_at IS NULL)""")

    op.execute("""INSERT INTO change_logs
        (id,project_id,entity_type,entity_id,action,operator_id,detail,created_at)
        VALUES ('v3-retention-unification-audit',NULL,'migration','g3a85b000001',
                'retention_unify',NULL,'回收站项目永久保留，旧归档只读保全；停止自动物理清理',CURRENT_TIMESTAMP)""")


def downgrade():
    raise RuntimeError('不得丢弃永久删除凭据；请恢复升级前一致加密备份')
