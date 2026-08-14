"""add key_encrypted to api_keys

Revision ID: 0002_add_key_encrypted
Revises: 0001_initial_schema
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0002_add_key_encrypted"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("key_encrypted", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "key_encrypted")
