"""rag_documents 增加解析入库状态字段

RAG 知识库「上传文档」改为文件上传 + 后台异步分块嵌入后，需要持久化每篇文档的
入库进度，供前端轮询展示阶段化进度（解析中/分块中/嵌入中/就绪/失败）与列表徽标。

为 ``rag_documents`` 增三列：
- ``status``：pending / parsing / chunking / embedding / ready / failed
- ``progress``：0-100
- ``parse_error``：失败原因

历史数据与同步入库（终端 JSON 文本入库、admin 既有文本入库）一律视为已就绪，
故三列均以 ``ready``/100/NULL 为 server_default，无需回填。

Revision ID: 0026_rag_doc_status
Revises: 0025_tool_call_logs_skill_fk
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0026_rag_doc_status"
down_revision = "0025_tool_call_logs_skill_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
    )
    op.add_column(
        "rag_documents",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "rag_documents",
        sa.Column("parse_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rag_documents", "parse_error")
    op.drop_column("rag_documents", "progress")
    op.drop_column("rag_documents", "status")
