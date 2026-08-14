"""add budget_cap_tokens to organizations/departments/teams/api_keys

Revision ID: 0003_add_budget_cap_tokens
Revises: 0002_add_key_encrypted
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0003_add_budget_cap_tokens"
down_revision = "0002_add_key_encrypted"
branch_labels = None
depends_on = None


_TABLES = ("organizations", "departments", "teams", "api_keys")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("budget_cap_tokens", sa.BigInteger(), nullable=True),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "budget_cap_tokens")
