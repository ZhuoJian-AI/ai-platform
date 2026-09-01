"""Allow a deleted department slug to be reused.

Revision ID: 0052_department_active_slug
Revises: 0051_multimodal_audio
Create Date: 2026-09-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0052_department_active_slug"
down_revision = "0051_multimodal_audio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_dept_org_slug", "departments", type_="unique")
    op.create_index(
        "uq_dept_org_slug_active",
        "departments",
        ["organization_id", "slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_dept_org_slug_active", table_name="departments")
    op.create_unique_constraint(
        "uq_dept_org_slug", "departments", ["organization_id", "slug"]
    )
