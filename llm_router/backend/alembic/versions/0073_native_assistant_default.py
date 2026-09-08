"""Make native Assistant Core the database default for new run rows.

Revision ID: 0073_native_assistant_default
Revises: 0072_agent_run_engine
Create Date: 2026-09-08

Historical ``dsh`` rows remain valid and queryable. The check constraint keeps
both values during the seven-day image rollback window; only the default for
new inserts changes.
"""

from alembic import op

revision = "0073_native_assistant_default"
down_revision = "0072_agent_run_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("agent_runs", "assistant_engine", server_default="native")


def downgrade() -> None:
    op.alter_column("agent_runs", "assistant_engine", server_default="dsh")
