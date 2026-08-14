"""ontology_folders / ontology_files 增加 created_by

终端「本体」功能需按「仅可删除/重命名/编辑自己创建的本体」授权（与 RAG 三表 0021、
技能 0022 同构），而 ontology_folders / ontology_files 当前无归属字段。本次为两表各加
一列 ``created_by``（终端用户 id，可空——历史数据与 admin 创建的资源保持 None），并建
索引以支持属主过滤。

Revision ID: 0023_ontology_created_by
Revises: 0022_skill_folder_created_by
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0023_ontology_created_by"
down_revision = "0022_skill_folder_created_by"
branch_labels = None
depends_on = None


_TABLES = ("ontology_folders", "ontology_files")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("created_by", sa.String(length=36), nullable=True))
        op.create_index(f"ix_{table}_created_by", table, ["created_by"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_created_by", table_name=table)
        op.drop_column(table, "created_by")
