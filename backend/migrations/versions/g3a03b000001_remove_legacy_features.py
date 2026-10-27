"""T03 remove retired features after verified, owner-isolated encrypted export."""

from alembic import op
import sqlalchemy as sa
from migrations.v3_retirement import retire_data

revision = "g3a03b000001"
down_revision = "g3a01b000001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError("T03删除前必须在线加密导出并核对原数据，不能离线跳过")
    retire_data(op.get_bind())
    for name in (
        "incident_actions",
        "incidents",
        "project_change_sets",
        "project_edit_history",
        "inbox_documents",
        "ai_chat_messages",
        "ai_chat_sessions",
        "ai_user_memories",
        "team_templates",
        "org_groups",
    ):
        op.drop_table(name)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("group_id")
        batch.drop_column("skills")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("is_demo")
        batch.drop_column("role_plan")
    op.execute(sa.text("DELETE FROM scheduler_watermarks WHERE job_id='daily_report'"))
    tokens = sa.table("ai_api_tokens", sa.column("id"), sa.column("scopes", sa.JSON()))
    for token_id, scopes in op.get_bind().execute(sa.select(tokens)):
        cleaned = [
            scope
            for scope in (scopes or [])
            if scope != "inbox:read" and not scope.startswith("change_sets:")
        ]
        if cleaned != scopes:
            op.get_bind().execute(
                tokens.update().where(tokens.c.id == token_id).values(scopes=cleaned)
            )


def downgrade():
    raise RuntimeError("T03保全导出不等于恢复原业务功能；回退请恢复升级前一致备份")
