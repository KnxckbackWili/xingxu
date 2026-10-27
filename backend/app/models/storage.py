"""Project-owned resumable uploads and explicit historical-file removal evidence."""
from sqlalchemy import Column,String,Integer,BigInteger,Boolean,Text,JSON,DateTime,ForeignKey,UniqueConstraint
from app.db import Base
from app.models import gen_uuid
from app.time_utils import utcnow
from sqlalchemy.orm import relationship

_bytes=lambda:BigInteger().with_variant(Integer,'sqlite')


class UploadSession(Base):
    __tablename__='upload_sessions'
    __table_args__=(UniqueConstraint('owner_id','client_uuid',name='uq_upload_owner_intent'),)
    id=Column(String(36),primary_key=True,default=gen_uuid)
    project_id=Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    owner_id=Column(String(36),ForeignKey('users.id',ondelete='SET NULL'))
    client_uuid=Column(String(64),nullable=False)
    state=Column(String(20),nullable=False,default='open')
    filename=Column(String(300),nullable=False)
    size=Column(_bytes(),nullable=False)
    sha256=Column(String(64),nullable=False)
    content_type=Column(String(100),nullable=False)
    chunk_size=Column(Integer,nullable=False)
    document_ids=Column(JSON,nullable=False)
    note=Column(Text,nullable=False,default='')
    entity_type=Column(String(20),nullable=False)
    entity_id=Column(String(36),nullable=False,default='')
    category=Column(String(50),nullable=False,default='')
    confidential=Column(Boolean,nullable=False,default=False)
    confidential_user_ids=Column(JSON,nullable=False,default=list)
    milestone_dates=Column(JSON,nullable=False,default=dict)
    attachment_id=Column(String(36),ForeignKey('attachments.id',ondelete='SET NULL'))
    created_at=Column(DateTime,nullable=False,default=utcnow)
    updated_at=Column(DateTime,nullable=False,default=utcnow)
    expires_at=Column(DateTime,nullable=False)


class UploadChunk(Base):
    __tablename__='upload_chunks'
    __table_args__=(UniqueConstraint('session_id','chunk_index',name='uq_upload_chunk_index'),)
    id=Column(String(36),primary_key=True,default=gen_uuid)
    project_id=Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    session_id=Column(String(36),ForeignKey('upload_sessions.id',ondelete='CASCADE'),nullable=False,index=True)
    chunk_index=Column(Integer,nullable=False)
    size=Column(Integer,nullable=False)
    sha256=Column(String(64),nullable=False)
    received_at=Column(DateTime,nullable=False,default=utcnow)


class FileCleanupReceipt(Base):
    __tablename__='file_cleanup_receipts'
    id=Column(String(36),primary_key=True,default=gen_uuid)
    project_id=Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    actor_id=Column(String(36),ForeignKey('users.id',ondelete='SET NULL'))
    actor_name=Column(String(100),nullable=False)
    keep_periods=Column(Integer,nullable=False)
    reason=Column(Text,nullable=False)
    preview_sha256=Column(String(64),nullable=False)
    policy=Column(JSON,nullable=False)
    applied_at=Column(DateTime,nullable=False,default=utcnow)


class FileRemovalRecord(Base):
    __tablename__='file_removal_records'
    id=Column(String(36),primary_key=True,default=gen_uuid)
    project_id=Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    attachment_id=Column(String(36),ForeignKey('attachments.id',ondelete='RESTRICT'),nullable=False,unique=True)
    receipt_id=Column(String(36),ForeignKey('file_cleanup_receipts.id',ondelete='RESTRICT'),nullable=False)
    stored_name=Column(String(100),nullable=False)
    filename=Column(String(300),nullable=False)
    sha256=Column(String(64),nullable=False)
    file_size=Column(_bytes(),nullable=False)
    removed_at=Column(DateTime,nullable=False,default=utcnow)
    removed_by=Column(String(36),ForeignKey('users.id',ondelete='SET NULL'))
    removed_by_name=Column(String(100),nullable=False)
    reason=Column(Text,nullable=False)
    receipt=relationship('FileCleanupReceipt',lazy='selectin')
