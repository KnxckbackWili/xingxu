"""T21: document requirements and project-independent blank form assets."""
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "g3a21b000001"
down_revision = "g3a20b000001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError("T21资料模板种子需读取现有模板，必须在线迁移")
    op.create_table("document_template_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("stored_name", sa.String(100), nullable=False, unique=True),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("uploaded_at", sa.DateTime()))
    table = op.create_table("document_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(36), sa.ForeignKey("templates.id", ondelete="CASCADE")),
        sa.Column("stage_key", sa.String(8), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("template_no", sa.String(100)),
        sa.Column("is_group", sa.Boolean(), nullable=False),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("document_requirements.id", ondelete="SET NULL")),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("scope", sa.String(20)), sa.Column("platform", sa.String(20)),
        sa.Column("timing_type", sa.String(24)), sa.Column("timing_event", sa.String(32)),
        sa.Column("timing_offset_hours", sa.Integer()), sa.Column("timing_weekday", sa.Integer()),
        sa.Column("trigger_type", sa.String(20)),
        sa.Column("confidential_default", sa.Boolean(), nullable=False),
        sa.Column("external_visible_default", sa.Boolean(), nullable=False),
        sa.Column("external_never_visible", sa.Boolean(), nullable=False),
        sa.Column("blank_file_id", sa.String(36), sa.ForeignKey("document_template_files.id", ondelete="SET NULL")),
        sa.Column("sort_order", sa.Integer(), nullable=False), sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()))
    op.create_index("ix_document_requirements_template_id", "document_requirements", ["template_id"])
    op.create_index("uq_document_requirement_default_code", "document_requirements", ["code"], unique=True,
                    sqlite_where=sa.text("template_id IS NULL"), postgresql_where=sa.text("template_id IS NULL"))
    op.create_index("uq_document_requirement_template_code", "document_requirements", ["template_id", "code"], unique=True,
                    sqlite_where=sa.text("template_id IS NOT NULL"), postgresql_where=sa.text("template_id IS NOT NULL"))
    seeds = json.loads((Path(__file__).resolve().parents[1] / "v3_document_requirements_seed.json").read_text())
    templates = [None] + list(op.get_bind().execute(sa.text("SELECT id FROM templates")).scalars())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for template_id in templates:
        ids = {row["code"]: str(uuid4()) for row in seeds}
        for seed in seeds:
            row = dict(seed)
            parent_code = row.pop("parent_code")
            op.get_bind().execute(table.insert().values(**row, id=ids[row["code"]], template_id=template_id,
                parent_id=ids[parent_code] if parent_code else None, blank_file_id=None, created_at=now, updated_at=now))


def downgrade():
    raise RuntimeError("资料定义与空白模板文件不可丢弃；回退请恢复升级前一致加密备份")
