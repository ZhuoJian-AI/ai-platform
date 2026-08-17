"""add timestamp defaults to scoped skill tables

Revision ID: 0036_skill_timestamp_defaults
Revises: 0035_scoped_code_skills
Create Date: 2026-08-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0036_skill_timestamp_defaults"
down_revision = "0035_scoped_code_skills"
branch_labels = None
depends_on = None


TABLES = (
    "scope_manager_assignments",
    "skill_versions",
    "skill_executions",
)


def upgrade() -> None:
    for table_name in TABLES:
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            existing_nullable=False,
        )
        op.alter_column(
            table_name,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table_name in TABLES:
        op.alter_column(
            table_name,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=None,
            existing_nullable=False,
        )
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=None,
            existing_nullable=False,
        )
