"""add organization_id to admins

为管理员增加 organization_id 字段，支持「组织管理员」角色绑定到单个组织。
- NULL 表示平台级账号（super_admin / 平台 admin / viewer），可跨组织操作
- 非 NULL 表示该管理员仅能管理被指派的组织（org_admin）
- 外键指向 organizations.id，ON DELETE SET NULL（组织删除时不级联删管理员）

Revision ID: 0010_admin_organization_id
Revises: 0009_add_default_org_flag
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0010_admin_organization_id"
down_revision = "0009_add_default_org_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admins",
        sa.Column(
            "organization_id",
            sa.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_admins_organization_id_organizations",
        "admins",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_admins_organization_id_organizations", "admins", type_="foreignkey"
    )
    op.drop_column("admins", "organization_id")
