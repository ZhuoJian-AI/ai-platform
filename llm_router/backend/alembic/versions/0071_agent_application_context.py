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
    # The staging garment assistant is the only live custom agent backed by the
    # retired Connector wrapper Skill.  Move it to the application's verified
    # Manifest page and remove only that wrapper dependency.  The guard uses
    # stable slugs plus organization equality so unrelated uploaded Skills and
    # agents remain untouched in every tenant.
    op.execute(
        sa.text(
            """
            UPDATE agents AS agent
            SET application_id = application.id,
                module_key = 'progress_dashboard',
                page_key = 'progress_dashboard.main',
                skill_ids = '[]'::jsonb
            FROM enterprise_applications AS application
            WHERE application.organization_id = agent.organization_id
              AND application.slug = 'garment-production-collaboration'
              AND agent.deleted_at IS NULL
              AND agent.application_id IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(agent.skill_ids) AS skill_id(value)
                  JOIN skill_folders AS folder ON folder.id::text = skill_id.value
                  WHERE folder.organization_id = agent.organization_id
                    AND folder.slug = 'aifabei-garment-production-api'
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_agents_application_id", table_name="agents")
    op.drop_column("agents", "page_key")
    op.drop_column("agents", "module_key")
    op.drop_column("agents", "application_id")
