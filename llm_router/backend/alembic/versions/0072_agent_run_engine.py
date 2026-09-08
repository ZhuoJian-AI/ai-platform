"""Persist the immutable Assistant Core engine selected for each run.

Revision ID: 0072_agent_run_engine
Revises: 0071_agent_application_context
Create Date: 2026-09-08

This is an expand-only, rollback-compatible change.  Older images ignore the
column and receive the server default ``dsh`` for the runs they create.
"""

import sqlalchemy as sa

from alembic import op

revision = "0072_agent_run_engine"
down_revision = "0071_agent_application_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "assistant_engine",
            sa.String(length=16),
            nullable=False,
            server_default="dsh",
        ),
    )
    op.create_check_constraint(
        "ck_agent_runs_assistant_engine",
        "agent_runs",
        "assistant_engine IN ('native','dsh')",
    )
    op.create_index(
        "ix_agent_runs_engine_status",
        "agent_runs",
        ["assistant_engine", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_engine_status", table_name="agent_runs")
    op.drop_constraint(
        "ck_agent_runs_assistant_engine",
        "agent_runs",
        type_="check",
    )
    op.drop_column("agent_runs", "assistant_engine")
