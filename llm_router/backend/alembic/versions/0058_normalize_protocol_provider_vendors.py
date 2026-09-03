"""Normalize protocol-compatible providers to protocol vendors.

Revision ID: 0058_protocol_provider_vendors
Revises: 0057_department_sort_order
Create Date: 2026-09-03
"""

import sqlalchemy as sa

from alembic import op

revision = "0058_protocol_provider_vendors"
down_revision = "0057_department_sort_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Xiaomi MiMo exposes OpenAI- and Anthropic-compatible endpoints; it is not
    # a separate wire protocol in the platform.  Preserve each row's configured
    # protocol and Base URL while removing the obsolete pseudo-vendor value.
    op.execute(sa.text("""
        UPDATE llm_providers
        SET vendor = CASE
                WHEN provider_type = 'anthropic' THEN 'anthropic'
                ELSE 'openai'
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE vendor = 'xiaomi_mimo'
    """))


def downgrade() -> None:
    # The old pseudo-vendor cannot be reconstructed reliably from a compatible
    # endpoint, and restoring it would reintroduce the removed public contract.
    pass
