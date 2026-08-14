"""data_systems + data_interfaces（数据接口，独立于连接器）

数据接口页的独立数据结构：系统（data_systems）+ 数据接口（data_interfaces）。
与连接器（connectors/endpoints，供技能绑定与 agent 调用）解耦——数据接口仅用于
管理端启用/禁用 + 查看输入输出样例。系统按 (organization_id, scope_type, scope_id) 节点作用域化。

Revision ID: 0019_data_interfaces
Revises: 0018_ontology_files
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0019_data_interfaces"
down_revision = "0018_ontology_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_systems",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="organization"),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "scope_type", "scope_id", "name", name="uq_data_system_scope_name"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_data_systems_org_scope", "data_systems", ["organization_id", "scope_type", "scope_id"])

    op.create_table(
        "data_interfaces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("data_system_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("params_schema", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_schema", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_system_id", "name", name="uq_data_interface_system_name"),
        sa.ForeignKeyConstraint(["data_system_id"], ["data_systems.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_data_interfaces_system", "data_interfaces", ["data_system_id"])


def downgrade() -> None:
    op.drop_index("ix_data_interfaces_system", table_name="data_interfaces")
    op.drop_table("data_interfaces")
    op.drop_index("ix_data_systems_org_scope", table_name="data_systems")
    op.drop_table("data_systems")
