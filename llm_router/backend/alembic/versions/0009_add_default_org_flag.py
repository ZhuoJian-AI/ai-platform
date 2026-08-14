"""add is_default flag to organizations

为组织增加 is_default 布尔字段，标记平台默认组织。
- 仅一个组织可为默认：创建部分唯一索引，WHERE is_default = TRUE 且未软删除
- 现有组织 is_default 默认为 FALSE（由超管在「组织管理」显式设定）

Revision ID: 0009_add_default_org_flag
Revises: 0008_tool_connector_schema
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0009_add_default_org_flag"
down_revision = "0008_tool_connector_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # 全平台至多一个默认组织（排除软删除行，便于删除后重新设定）
    op.create_index(
        "uq_organizations_is_default",
        "organizations",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default = TRUE AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_organizations_is_default", table_name="organizations")
    op.drop_column("organizations", "is_default")
