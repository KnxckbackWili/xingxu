"""T26: explicit project-owner controlled confidentiality, without implicit grants."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'g3a26b000001'
down_revision = 'g3a32b000001'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('attachments', 'project_document_definitions', 'project_documents'):
        op.add_column(table, sa.Column('confidential_user_ids', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=False, server_default=sa.text("'[]'")))
    for table in ('attachments', 'project_document_definitions'):
        op.add_column(table, sa.Column('access_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('attachments', sa.Column('confidential_explicit', sa.Boolean(), nullable=False, server_default=sa.false()))
    # Frozen SQL: T22 only derived this flag on submissions; standalone private
    # files retain an independent restriction. Never invent grants to uploaders,
    # submitters, administrators, technical managers or other former implicit readers.
    op.execute(sa.text('''UPDATE attachments SET confidential_explicit = true
        WHERE confidential = true AND NOT EXISTS (
            SELECT 1 FROM document_versions v JOIN project_documents d ON d.id = v.project_document_id
            WHERE v.attachment_id = attachments.id AND d.confidential = true)'''))
    for table, flag in (('document_requirements', 'confidential_default'),
                        ('project_document_definitions', 'confidential_default'),
                        ('project_documents', 'confidential')):
        op.execute(sa.text(f'''UPDATE {table} SET {flag} = true, external_never_visible = true,
            {'external_visible_default' if table != 'project_documents' else 'external_visible'} = false
            WHERE code IN ('6.11.6','6.11.6a','6.11.6b','6.11.6c')'''))
    # Old submitted instances were not rewritten when their definition changed.
    # A family is private if either side was private; never expose the same name,
    # blank or an older period through the other side of that relationship.
    op.execute(sa.text('''UPDATE project_document_definitions SET confidential_default = true
        WHERE EXISTS (SELECT 1 FROM project_documents d
            WHERE d.definition_id = project_document_definitions.id AND d.confidential = true)'''))
    op.execute(sa.text('''UPDATE project_documents SET confidential = true
        WHERE EXISTS (SELECT 1 FROM project_document_definitions r
            WHERE r.id = project_documents.definition_id AND r.confidential_default = true)'''))
    for table, flag, external in (('project_document_definitions','confidential_default','external_visible_default'),
                                  ('project_documents','confidential','external_visible')):
        op.execute(sa.text(f'UPDATE {table} SET external_never_visible = true, {external} = false WHERE {flag} = true'))
    op.execute(sa.text('''UPDATE attachments SET confidential = true WHERE EXISTS (
        SELECT 1 FROM document_versions v JOIN project_documents d ON d.id = v.project_document_id
        WHERE v.attachment_id = attachments.id AND d.confidential = true)'''))


def downgrade():
    raise RuntimeError('保密授权与审计不能丢弃；回退请恢复升级前一致加密备份')
