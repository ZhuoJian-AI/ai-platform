"""add password to users

为组织用户（终端成员）新增密码登录体系：
- password_hash：bcrypt 哈希，nullable（存量用户无密码，需管理员重置后方可密码登录）
- must_change_password：重置/创建后强制下次登录改密

Revision ID: 0011_user_password
Revises: 0010_admin_organization_id
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0011_user_password"
down_revision = "0010_admin_organization_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "password_hash")
