"""rename users.email to username

将终端用户（users 表）的登录标识由 email 改为 username，与管理端一致：
用户名不再使用邮箱，同一组织内不可同名，不同组织之间可以同名。

users 的 organization_id 恒非空，故用单一复合唯一约束 (organization_id, username)
即可表达「组织内唯一」；迁移 0001 原建的 uq_user_org_email 被替换为
uq_user_org_username。

Revision ID: 0014_user_username
Revises: 0013_terminal_and_scoping
Create Date: 2026-06-29
"""

from alembic import op

# revision identifiers
revision = "0014_user_username"
down_revision = "0013_terminal_and_scoping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users RENAME COLUMN email TO username")
    op.drop_constraint("uq_user_org_email", "users", type_="unique")
    op.create_unique_constraint(
        "uq_user_org_username", "users", ["organization_id", "username"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_org_username", "users", type_="unique")
    op.create_unique_constraint(
        "uq_user_org_email", "users", ["organization_id", "email"]
    )
    op.execute("ALTER TABLE users RENAME COLUMN username TO email")
