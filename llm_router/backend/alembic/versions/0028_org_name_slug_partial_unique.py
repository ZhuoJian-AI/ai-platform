"""organizations.name / slug 唯一约束改为 partial（排除软删行）

原约束 ``organizations_name_key`` / ``organizations_slug_key`` 为非 partial 唯一约束，
导致软删组织仍占用 name/slug 槽位，新组织/重命名时无法复用同名同 slug。

改为 partial unique index（``WHERE deleted_at IS NULL``）：
- 软删组织不再阻塞新组织复用同名 / 同 slug；
- 未软删组织间仍保证 name / slug 在平台内唯一。

同时更新 ORM model ``Organization`` 的 ``name`` / ``slug`` 字段以反映新行为
（移除 ``unique=True``，partial 唯一性由 DB 索引承担）。

Revision ID: 0028_org_name_slug_partial
Revises: 0027_provider_scope
Create Date: 2026-07-10
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0028_org_name_slug_partial"
down_revision = "0027_provider_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # name：drop 老约束 → 建 partial unique index
    op.drop_constraint("organizations_name_key", "organizations", type_="unique")
    op.create_index(
        "uq_organizations_name_active",
        "organizations",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # slug：同上
    op.drop_constraint("organizations_slug_key", "organizations", type_="unique")
    op.create_index(
        "uq_organizations_slug_active",
        "organizations",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_organizations_slug_active", table_name="organizations")
    op.create_unique_constraint("organizations_slug_key", "organizations", ["slug"])
    op.drop_index("uq_organizations_name_active", table_name="organizations")
    op.create_unique_constraint("organizations_name_key", "organizations", ["name"])
