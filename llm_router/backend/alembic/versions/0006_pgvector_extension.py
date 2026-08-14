"""pgvector extension

为智能体平台 RAG 向量检索启用 PostgreSQL vector 扩展。docker-compose 已切换至
pgvector/pgvector:pg16 镜像（预装 vector），本迁移在目标库中激活扩展。

后续迁移（0007+）建 agent / tool / monitor 相关表时，RagChunk.embedding 使用
pgvector.sqlalchemy.Vector 类型，依赖本扩展。

Revision ID: 0006_pgvector_extension
Revises: 0005_drop_builtin_dlp_rules
Create Date: 2026-06-28
"""

from alembic import op

# revision identifiers
revision = "0006_pgvector_extension"
down_revision = "0005_drop_builtin_dlp_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # 不主动 drop 扩展：可能被既有向量列依赖；仅在新库干净回滚时手动处理。
    pass
