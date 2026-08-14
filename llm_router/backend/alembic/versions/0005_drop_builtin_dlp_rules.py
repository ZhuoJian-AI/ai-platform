"""drop retired builtin DLP rules

下线以下内置全局 DLP 规则（已从 patterns 库移除）：
- 美国社会安全号
- ICD疾病编码
- 医疗记录号
- 诊断关键词

ensure_default_dlp_rules 只增不删，故用迁移对已落库的同名全局规则做软删除
（scope_type='global' 且 organization_id IS NULL），保留行以维持审计引用。

Revision ID: 0005_drop_builtin_dlp_rules
Revises: 0004_remove_default_org
Create Date: 2026-06-23
"""

from alembic import op

# revision identifiers
revision = "0005_drop_builtin_dlp_rules"
down_revision = "0004_remove_default_org"
branch_labels = None
depends_on = None

RETIRED_RULE_NAMES = (
    "美国社会安全号",
    "ICD疾病编码",
    "医疗记录号",
    "诊断关键词",
)


def upgrade() -> None:
    names_sql = ", ".join(f"'{n}'" for n in RETIRED_RULE_NAMES)
    op.execute(
        "UPDATE dlp_rules SET deleted_at = NOW() "
        f"WHERE scope_type = 'global' AND organization_id IS NULL "
        f"AND deleted_at IS NULL AND name IN ({names_sql})"
    )


def downgrade() -> None:
    # 不可逆恢复：规则已从内置库移除，重新启用仅会再被本迁移软删除。
    names_sql = ", ".join(f"'{n}'" for n in RETIRED_RULE_NAMES)
    op.execute(
        "UPDATE dlp_rules SET deleted_at = NULL "
        f"WHERE scope_type = 'global' AND organization_id IS NULL "
        f"AND name IN ({names_sql})"
    )
