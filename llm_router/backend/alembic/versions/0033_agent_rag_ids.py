"""agents 表加 rag_collection_ids（JSONB 数组）—— 智能体模板绑定多个 RAG 集合

终端 general 模式的 RAG 来自任务 config（rag_collection_ids 复数），原本不从 agent
模板继承。本次给 Agent 加 rag_collection_ids 复数列，使模板能绑多个 RAG，并在
load_config general 分支于任务未指定 RAG 时继承（与 skill_ids 同范式）。

旧单 FK rag_collection_id 保留，供管理端测试广场（agent 模式）单 RAG 使用，不动。

Revision ID: 0033_agent_rag_ids
Revises: 0032_agent_scope
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0033_agent_rag_ids"
down_revision = "0032_agent_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "rag_collection_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "rag_collection_ids")
