"""agent_run_events 表 — SSE 事件流落库供 resume 回放

终端任务执行改为后台 detach 跑（runner.py stream_general_agent），每条 SSE 事件
（step/trace/phase/tool_call/tool_result/text/done/final/error）边产边落库，
使「客户端断连 → GET /terminal/tasks/{id}/stream 回放已落库 + 续接 live」成为可能。

Revision ID: 0031_agent_run_events
Revises: 0030_dlp_no_global_org_seed
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0031_agent_run_events"
down_revision = "0030_dlp_no_global_org_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])
    op.create_index("ix_agent_run_events_task_id", "agent_run_events", ["task_id"])
    op.create_index(
        "ix_agent_run_events_run_seq", "agent_run_events", ["run_id", "seq"]
    )
    op.create_index(
        "ix_agent_run_events_task_seq", "agent_run_events", ["task_id", "seq"]
    )
    # task_id 无 FK 约束（与 agent_runs.task_id 一致：存 UUID 字符串，不强约束），
    # 由应用层保证；ondelete 行为靠 agent_runs 级联 + 应用清理。


def downgrade() -> None:
    op.drop_index("ix_agent_run_events_task_seq", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_run_seq", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_task_id", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_run_id", table_name="agent_run_events")
    op.drop_table("agent_run_events")
