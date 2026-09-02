"""Add administrator-managed department ordering.

Revision ID: 0055_department_sort_order
Revises: 0054_auth_cleanup
Create Date: 2026-09-02
"""

import sqlalchemy as sa

from alembic import op

revision = "0055_department_sort_order"
down_revision = "0054_auth_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute(sa.text("""
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY organization_id
                    ORDER BY created_at, id
                ) - 1 AS position
            FROM departments
            WHERE deleted_at IS NULL
        )
        UPDATE departments AS department
        SET sort_order = ranked.position
        FROM ranked
        WHERE department.id = ranked.id
    """))
    op.create_index(
        "ix_departments_org_sort_order",
        "departments",
        ["organization_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_departments_org_sort_order", table_name="departments")
    op.drop_column("departments", "sort_order")
