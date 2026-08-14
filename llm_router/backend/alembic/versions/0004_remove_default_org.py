"""remove default organization; global DLP rules become org-less

- dlp_rules.organization_id 改为可空
- 已有 scope_type='global' 的 DLP 规则 organization_id 置 NULL
- 软删除 slug='default' 的默认组织

Revision ID: 0004_remove_default_org
Revises: 0003_add_budget_cap_tokens
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0004_remove_default_org"
down_revision = "0003_add_budget_cap_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 全局 DLP 规则脱离默认组织
    op.alter_column(
        "dlp_rules",
        "organization_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=True,
    )
    op.execute(
        "UPDATE dlp_rules SET organization_id = NULL WHERE scope_type = 'global'"
    )

    # 2. 软删除默认组织（保留行以维持引用完整性，list_organizations 已过滤 deleted_at）
    op.execute(
        "UPDATE organizations SET deleted_at = NOW() "
        "WHERE slug = 'default' AND deleted_at IS NULL"
    )


def downgrade() -> None:
    # 不可逆：恢复默认组织无意义，仅还原可空性
    op.alter_column(
        "dlp_rules",
        "organization_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=False,
    )
