"""Allow a terminal user to belong to multiple departments.

Revision ID: 0046_user_multi_departments
Revises: 0045_subsystem_pages_events
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0046_user_multi_departments"
down_revision = "0045_subsystem_pages_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_department_memberships",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "department_id"),
    )
    op.create_index(
        "ix_user_department_memberships_department_id",
        "user_department_memberships",
        ["department_id"],
    )
    op.execute(sa.text("""
        INSERT INTO user_department_memberships (user_id, department_id)
        SELECT id, department_id
        FROM users
        WHERE department_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """))


def downgrade() -> None:
    op.drop_index(
        "ix_user_department_memberships_department_id",
        table_name="user_department_memberships",
    )
    op.drop_table("user_department_memberships")
