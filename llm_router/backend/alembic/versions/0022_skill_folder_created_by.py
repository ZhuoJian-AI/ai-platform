"""skill_folders 增加 created_by

终端「技能」功能需按「仅可删除/重命名自己创建的技能」授权（与 RAG 三表 0021 同构），
而 skill_folders 当前无归属字段。本次加一列 ``created_by``（终端用户 id，可空——历史数据
与 admin 创建的资源保持 None），并建索引以支持属主过滤。

Revision ID: 0022_skill_folder_created_by
Revises: 0021_rag_created_by
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0022_skill_folder_created_by"
down_revision = "0021_rag_created_by"
branch_labels = None
depends_on = None


_TABLE = "skill_folders"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("created_by", sa.String(length=36), nullable=True))
    op.create_index(f"ix_{_TABLE}_created_by", _TABLE, ["created_by"])


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_created_by", table_name=_TABLE)
    op.drop_column(_TABLE, "created_by")
