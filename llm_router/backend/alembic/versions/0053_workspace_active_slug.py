"""Allow a deleted workspace slug to be reused by a new workspace.

Revision ID: 0053_workspace_active_slug
Revises: 0052_department_active_slug
Create Date: 2026-09-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0053_workspace_active_slug"
down_revision = "0052_department_active_slug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_workspace_org_slug", "workspaces", type_="unique")
    op.create_index(
        "uq_workspace_org_slug_active",
        "workspaces",
        ["organization_id", "slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_org_slug_active", table_name="workspaces")
    op.create_unique_constraint(
        "uq_workspace_org_slug", "workspaces", ["organization_id", "slug"]
    )
