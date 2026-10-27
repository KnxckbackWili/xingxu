"""T25: resumable evidence uploads and explicit historical-file removal receipts."""
from alembic import op
import sqlalchemy as sa

revision='g3a25b000001'
down_revision='g3a26b000001'
branch_labels=None
depends_on=None


def _id():return sa.Column('id',sa.String(36),primary_key=True)
def _project():return sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id',ondelete='CASCADE'),nullable=False)
def _user(name):return sa.Column(name,sa.String(36),sa.ForeignKey('users.id',ondelete='SET NULL'))
def _bytes():return sa.BigInteger().with_variant(sa.Integer(),'sqlite')
def _text(name,size,nullable=False):return sa.Column(name,sa.String(size),nullable=nullable)
def _date(name):return sa.Column(name,sa.DateTime(),nullable=False)


def upgrade():
    # SQLite INTEGER already stores signed 64-bit values; avoid destructive
    # batch rebuilds and preserve every existing evidence FK/index in place.
    if op.get_context().dialect.name!='sqlite':
        for table in ('attachments','document_template_files','template_docs'):
            op.alter_column(table,'file_size',existing_type=sa.Integer(),type_=sa.BigInteger())
    op.create_table('upload_sessions',_id(),_project(),_user('owner_id'),_text('client_uuid',64),_text('state',20),
        _text('filename',300),sa.Column('size',_bytes(),nullable=False),_text('sha256',64),_text('content_type',100),
        sa.Column('chunk_size',sa.Integer(),nullable=False),sa.Column('document_ids',sa.JSON(),nullable=False),
        sa.Column('note',sa.Text(),nullable=False),_text('entity_type',20),_text('entity_id',36),_text('category',50),
        sa.Column('confidential',sa.Boolean(),nullable=False),sa.Column('confidential_user_ids',sa.JSON(),nullable=False),
        sa.Column('milestone_dates',sa.JSON(),nullable=False),
        sa.Column('attachment_id',sa.String(36),sa.ForeignKey('attachments.id',ondelete='SET NULL')),
        _date('created_at'),_date('updated_at'),_date('expires_at'),
        sa.UniqueConstraint('owner_id','client_uuid',name='uq_upload_owner_intent'))
    op.create_index('ix_upload_sessions_project_id','upload_sessions',['project_id'])
    op.create_table('upload_chunks',_id(),_project(),
        sa.Column('session_id',sa.String(36),sa.ForeignKey('upload_sessions.id',ondelete='CASCADE'),nullable=False),
        sa.Column('chunk_index',sa.Integer(),nullable=False),sa.Column('size',sa.Integer(),nullable=False),
        _text('sha256',64),_date('received_at'),sa.UniqueConstraint('session_id','chunk_index',name='uq_upload_chunk_index'))
    op.create_index('ix_upload_chunks_project_id','upload_chunks',['project_id'])
    op.create_index('ix_upload_chunks_session_id','upload_chunks',['session_id'])
    op.create_table('file_cleanup_receipts',_id(),_project(),_user('actor_id'),_text('actor_name',100),
        sa.Column('keep_periods',sa.Integer(),nullable=False),sa.Column('reason',sa.Text(),nullable=False),
        _text('preview_sha256',64),sa.Column('policy',sa.JSON(),nullable=False),_date('applied_at'))
    op.create_index('ix_file_cleanup_receipts_project_id','file_cleanup_receipts',['project_id'])
    op.create_table('file_removal_records',_id(),_project(),
        sa.Column('attachment_id',sa.String(36),sa.ForeignKey('attachments.id',ondelete='RESTRICT'),nullable=False,unique=True),
        sa.Column('receipt_id',sa.String(36),sa.ForeignKey('file_cleanup_receipts.id',ondelete='RESTRICT'),nullable=False),
        _text('stored_name',100),_text('filename',300),_text('sha256',64),sa.Column('file_size',_bytes(),nullable=False),
        _date('removed_at'),_user('removed_by'),_text('removed_by_name',100),sa.Column('reason',sa.Text(),nullable=False))
    op.create_index('ix_file_removal_records_project_id','file_removal_records',['project_id'])


def downgrade():
    raise RuntimeError('上传幂等凭据与历史文件清理是审计事实，请恢复升级前一致备份')
