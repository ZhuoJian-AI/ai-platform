"""workspace_files 增加 Office/PDF 解析结果字段

Revision ID: 0034_workspace_file_parsing
Revises: 0033_agent_rag_ids
Create Date: 2026-08-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0034_workspace_file_parsing"
down_revision = "0033_agent_rag_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_files", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column(
        "workspace_files",
        sa.Column("parse_status", sa.String(length=20), nullable=False, server_default="unparsed"),
    )
    op.add_column("workspace_files", sa.Column("parse_kind", sa.String(length=20), nullable=True))
    op.add_column("workspace_files", sa.Column("parse_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_files", "parse_error")
    op.drop_column("workspace_files", "parse_kind")
    op.drop_column("workspace_files", "parse_status")
    op.drop_column("workspace_files", "extracted_text")
