"""rag_collections / rag_documents / rag_folders 增加 created_by

终端「知识库」功能需要按「仅可删除/重命名/编辑自己创建的资源」授权，
而 RAG 三表当前无归属字段。本次为三表各加一列 ``created_by``（终端用户 id，
可空——历史数据与 admin 创建的资源保持 None），并建索引以支持属主过滤。

Revision ID: 0021_rag_created_by
Revises: 0020_skill_folders
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0021_rag_created_by"
down_revision = "0020_skill_folders"
branch_labels = None
depends_on = None


_TABLES = ("rag_collections", "rag_documents", "rag_folders")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("created_by", sa.String(length=36), nullable=True),
        )
        op.create_index(f"ix_{table}_created_by", table, ["created_by"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_created_by", table_name=table)
        op.drop_column(table, "created_by")
