"""rename admins.email to username, switch to per-org / platform unique

将 admins.email（全局唯一）改为 username，并把唯一性约束改为：
- 组织级账号（organization_id IS NOT NULL）：(organization_id, username) 组织内唯一
- 平台级账号（organization_id IS NULL）：username 全局唯一

由此支持「用户名不再使用邮箱」：同一组织内不可同名，不同组织之间可以同名；
平台级账号（root / 平台 admin / viewer）仍全局唯一。

Revision ID: 0012_admin_username
Revises: 0011_user_password
Create Date: 2026-06-29
"""

from alembic import op

# revision identifiers
revision = "0012_admin_username"
down_revision = "0011_user_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 列重命名 email -> username（PG 会自动带上其上的唯一约束/索引引用）
    op.execute("ALTER TABLE admins RENAME COLUMN email TO username")

    # 2) 删除原全局唯一约束（0001 由 unique=True 自动命名为 admins_email_key）
    op.execute("ALTER TABLE admins DROP CONSTRAINT IF EXISTS admins_email_key")
    # 兜底：若历史以唯一索引形式存在
    op.execute("DROP INDEX IF EXISTS admins_email_key")

    # 3) 组织内唯一（仅对绑定了组织的账号生效）
    op.execute(
        "CREATE UNIQUE INDEX uq_admins_username_org "
        "ON admins (organization_id, username) WHERE organization_id IS NOT NULL"
    )
    # 4) 平台级全局唯一（仅对未绑定组织的账号生效）
    op.execute(
        "CREATE UNIQUE INDEX uq_admins_username_platform "
        "ON admins (username) WHERE organization_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_admins_username_platform")
    op.execute("DROP INDEX IF EXISTS uq_admins_username_org")
    op.execute("ALTER TABLE admins RENAME COLUMN username TO email")
    # 恢复全局唯一约束（若存量数据已含跨组织同名 username，重建会失败——downgrade 仅供参考）
    op.execute("ALTER TABLE admins ADD CONSTRAINT admins_email_key UNIQUE (email)")
