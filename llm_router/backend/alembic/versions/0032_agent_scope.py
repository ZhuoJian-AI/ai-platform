"""agents 表加 scope_type / scope_id / created_by —— 智能体部门级挂载

为管理端「智能体」三栏页与终端「选智能体」下拉做铺垫：把 org 级 Agent 改为
可按 organization/department/team/user 作用域化，slug 唯一约束随之改为按 scope。

- agents 加 scope_type（String(20) NOTNULL default 'organization'，存量行全落 org 级，不破旧唯一约束语义）
- agents 加 scope_id（String(36) nullable + index）
- agents 加 created_by（FK users.id SET NULL + index）
- 唯一约束 uq_agent_org_slug(org, slug) → uq_agent_scope_slug(org, scope_type, scope_id, slug)
  （与 skill_folders.uq_skill_folder_scope_slug 同范式）

Revision ID: 0032_agent_scope
Revises: 0031_agent_run_events
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0032_agent_scope"
down_revision = "0031_agent_run_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="organization"),
    )
    op.add_column(
        "agents",
        sa.Column("scope_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("created_by", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_agents_scope_id", "agents", ["scope_id"])
    op.create_index("ix_agents_created_by", "agents", ["created_by"])
    # 唯一约束：org 级 → 按 scope（存量行 scope_type='organization'/scope_id=NULL 等价保留）
    op.drop_constraint("uq_agent_org_slug", "agents", type_="unique")
    op.create_unique_constraint(
        "uq_agent_scope_slug", "agents",
        ["organization_id", "scope_type", "scope_id", "slug"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_scope_slug", "agents", type_="unique")
    op.create_unique_constraint("uq_agent_org_slug", "agents", ["organization_id", "slug"])
    op.drop_index("ix_agents_created_by", table_name="agents")
    op.drop_index("ix_agents_scope_id", table_name="agents")
    op.drop_column("agents", "created_by")
    op.drop_column("agents", "scope_id")
    op.drop_column("agents", "scope_type")
