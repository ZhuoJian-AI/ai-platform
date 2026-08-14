"""移除模型别名（ModelAlias）机制

别名层（``model_aliases`` 表 + ``router.resolve_model`` 解析）已废弃：agent/task 的
``model_alias`` 字段此后直接持有真实模型 id（如 ``glm-5.2`` / ``claude-sonnet-4``），
路由侧 ``find_provider`` 按真实 id 匹配 provider，不再有别名查表层。

本迁移：
- upgrade：先把 ``agents.model_alias`` 列里仍是别名值（命中 ``model_aliases`` 表）的行
  原地替换为其 ``target_model``（保行为——转换前后 resolve 结果一致），再 drop ``model_aliases`` 表。
- downgrade：按 0001 schema 重建 ``model_aliases`` 表（不回填数据；别名需重跑 seed 恢复）。

注：``tasks.config`` JSON 里的 ``model_alias`` 若仍是别名值不在本迁移处理范围——demo 任务
即用即弃，重跑 seed 后新任务用真实 id。后端运行代码（``resolve_model`` 函数、ModelAlias
模型、``/model-aliases`` CRUD）已在应用层删除，见本仓库 ``app/`` 改动。

Revision ID: 0029_drop_model_aliases
Revises: 0028_org_name_slug_partial_unique
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0029_drop_model_aliases"
down_revision = "0028_org_name_slug_partial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 数据迁移：agents.model_alias 里仍是别名值的，原地替换为 model_aliases.target_model
    op.execute(
        """
        UPDATE agents AS a
           SET model_alias = ma.target_model
          FROM model_aliases AS ma
         WHERE ma.organization_id = a.organization_id
           AND ma.alias = a.model_alias
        """
    )
    # 2) 删除别名表
    op.drop_table("model_aliases")


def downgrade() -> None:
    # 按 0001 schema 重建表（不回填别名数据）
    op.create_table(
        "model_aliases",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("target_model", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "alias", name="uq_alias_org_alias"),
    )
