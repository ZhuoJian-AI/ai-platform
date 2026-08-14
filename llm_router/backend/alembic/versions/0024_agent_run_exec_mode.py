"""agent_runs 增加 exec_mode（craft/ask/plan）

终端通用智能体任务（general 模式）落库时 ``agent_id`` 为空，监控台「按智能体明细」
原按 ``agent_id`` 分组，导致这些运行被标成"(已删除)"。本次为 ``agent_runs`` 增列
``exec_mode``，使明细可按 通用-Craft / 通用-Plan / 通用-Ask 三类拆分。

- general 运行：从 ``tasks.config->>'exec_mode'`` 回填（agent_id 为空且 task_id 非空）。
- agent 运行（管理端测试广场）：无 exec_mode 概念，保留 server_default 'craft'。

Revision ID: 0024_agent_run_exec_mode
Revises: 0023_ontology_created_by
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0024_agent_run_exec_mode"
down_revision = "0023_ontology_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("exec_mode", sa.String(length=20), nullable=False, server_default="craft"),
    )
    # 回填终端通用运行（agent_id 为空）的 exec_mode
    op.execute(
        """
        UPDATE agent_runs AS ar SET exec_mode = t.config->>'exec_mode'
        FROM tasks AS t
        WHERE ar.task_id = t.id
          AND ar.agent_id IS NULL
          AND t.config->>'exec_mode' IN ('craft', 'ask', 'plan')
        """
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "exec_mode")
