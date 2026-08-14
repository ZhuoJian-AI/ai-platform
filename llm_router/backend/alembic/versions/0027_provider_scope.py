"""llm_providers 增加作用域层级字段（组织/部门/团队）

模型提供商此前仅 organization_id 一级归属，调用解析只按组织过滤。为支持
「团队级 > 部门级 > 组织级」优先级与继承（团队调用方可继承部门/组织级 provider），
为 ``llm_providers`` 增三列：

- ``scope_type``：organization / department / team，老数据一律视为 organization
- ``department_id``：部门级 provider 绑定部门（可空，ON DELETE SET NULL）
- ``team_id``：团队级 provider 绑定团队（可空，ON DELETE SET NULL）

老数据 server_default='organization' + NULL dept/team 即可，无需回填。

Revision ID: 0027_provider_scope
Revises: 0026_rag_doc_status
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0027_provider_scope"
down_revision = "0026_rag_doc_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_providers",
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="organization"),
    )
    op.add_column(
        "llm_providers",
        sa.Column(
            "department_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_providers",
        sa.Column(
            "team_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_llm_providers_scope_type", "llm_providers", ["scope_type"])
    op.create_index("ix_llm_providers_department_id", "llm_providers", ["department_id"])
    op.create_index("ix_llm_providers_team_id", "llm_providers", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_providers_team_id", table_name="llm_providers")
    op.drop_index("ix_llm_providers_department_id", table_name="llm_providers")
    op.drop_index("ix_llm_providers_scope_type", table_name="llm_providers")
    op.drop_column("llm_providers", "team_id")
    op.drop_column("llm_providers", "department_id")
    op.drop_column("llm_providers", "scope_type")
