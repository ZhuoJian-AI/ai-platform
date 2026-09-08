"""Add optional Manifest page context to custom agents.

Revision ID: 0071_agent_application_context
Revises: 0070_runtime_auto_release
Create Date: 2026-09-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0071_agent_application_context"
down_revision = "0070_runtime_auto_release"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("enterprise_applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("agents", sa.Column("module_key", sa.String(length=128), nullable=True))
    op.add_column("agents", sa.Column("page_key", sa.String(length=128), nullable=True))
    op.create_index("ix_agents_application_id", "agents", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_agents_application_id", table_name="agents")
    op.drop_column("agents", "page_key")
    op.drop_column("agents", "module_key")
    op.drop_column("agents", "application_id")
