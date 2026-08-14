"""drop viewer (只读) role from admins / users

平台取消「只读 viewer」角色：
- admins.role='viewer' → 'admin'（平台级写权限；当前无此存量）
- users.role='viewer'  → 'member'（普通成员）

role 列为自由字符串（非 enum），无需改 schema；本迁移仅做数据归一，
确保去除 viewer 后不残留孤立角色值。

Revision ID: 0015_drop_viewer_role
Revises: 0014_user_username
Create Date: 2026-06-29
"""

from alembic import op

# revision identifiers
revision = "0015_drop_viewer_role"
down_revision = "0014_user_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE admins SET role = 'admin' WHERE role = 'viewer'")
    op.execute("UPDATE users SET role = 'member' WHERE role = 'viewer'")


def downgrade() -> None:
    # 不可逆：无法还原原始 viewer 与非 viewer 的区分，downgrade 不做回滚
    pass
