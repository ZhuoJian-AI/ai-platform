"""rag_folders table + rag_documents.folder_path

RAG 知识库文件夹实体：与 rag_documents 平行，path 为相对集合根的 POSIX 路径，
嵌套靠路径段表达，支持空文件夹与按文件夹为单位的级联删除。同时给 rag_documents
增加 folder_path 列以归属文件夹。

Revision ID: 0017_rag_folders_doc_path
Revises: 0016_workspace_folders
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0017_rag_folders_doc_path"
down_revision = "0016_workspace_folders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "path", name="uq_ragfolder_path"),
        sa.ForeignKeyConstraint(["collection_id"], ["rag_collections.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_rag_folders_collection_id", "rag_folders", ["collection_id"])

    op.add_column(
        "rag_documents",
        sa.Column("folder_path", sa.String(length=1024), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("rag_documents", "folder_path")
    op.drop_index("ix_rag_folders_collection_id", table_name="rag_folders")
    op.drop_table("rag_folders")
