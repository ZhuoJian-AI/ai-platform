"""Enforce one organizational department per user.

Revision ID: 0049_single_user_department
Revises: 0048_ecs_publisher_runtime
Create Date: 2026-09-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0049_single_user_department"
down_revision = "0048_ecs_publisher_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the users.department_id value as the sole source of organizational
    # membership. Application and submodule visibility remains in grant tables.
    op.execute(sa.text("""
        DELETE FROM user_department_memberships AS membership
        USING users AS app_user
        WHERE membership.user_id = app_user.id
          AND (
            app_user.department_id IS NULL
            OR membership.department_id <> app_user.department_id
          )
    """))
    op.execute(sa.text("""
        INSERT INTO user_department_memberships (user_id, department_id)
        SELECT id, department_id
        FROM users
        WHERE department_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """))
    op.create_unique_constraint(
        "uq_user_department_memberships_user_id",
        "user_department_memberships",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_user_department_memberships_user_id",
        "user_department_memberships",
        type_="unique",
    )
