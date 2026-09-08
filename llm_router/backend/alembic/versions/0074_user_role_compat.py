"""Keep legacy users.role compatible while UserRole is authoritative.

Revision ID: 0074_user_role_compat
Revises: 0073_native_assistant_default
Create Date: 2026-09-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0074_user_role_compat"
down_revision = "0073_native_assistant_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Upgraded databases still contain the historical NOT NULL column even
    # though authorization has moved to user_roles.  A server default lets
    # both old and new application images create employees during expand.
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=50),
        existing_nullable=False,
        server_default=sa.text("'member'"),
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=50),
        existing_nullable=False,
        server_default=None,
    )
