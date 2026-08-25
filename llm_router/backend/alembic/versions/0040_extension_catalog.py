"""developer extension discovery catalog

Revision ID: 0040_extension_catalog
Revises: 0039_platform_extensions
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0040_extension_catalog"
down_revision = "0039_platform_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_extension_catalog_entries",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("external_key", sa.String(512), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("package_name", sa.String(255), nullable=True),
        sa.Column("version", sa.String(100), nullable=True),
        sa.Column("available_versions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("repository", sa.Text(), nullable=True),
        sa.Column("homepage", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("layer", sa.String(50), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("operation", sa.String(30), nullable=False, server_default=sa.text("'add'")),
        sa.Column("kind", sa.String(30), nullable=False, server_default=sa.text("'adapter_required'")),
        sa.Column("trust_level", sa.String(30), nullable=False, server_default=sa.text("'community'")),
        sa.Column("runtime_requirements", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("compatibility_status", sa.String(30), nullable=False, server_default=sa.text("'needs_adapter'")),
        sa.Column("compatibility_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "external_key", name="uq_platform_extension_catalog_provider_key"),
    )
    for column in ("provider", "slug", "package_name", "category", "layer", "compatibility_status", "is_active"):
        op.create_index(
            f"ix_platform_extension_catalog_entries_{column}",
            "platform_extension_catalog_entries",
            [column],
        )
    op.create_index(
        "ix_platform_extension_catalog_layer_status",
        "platform_extension_catalog_entries",
        ["layer", "compatibility_status"],
    )


def downgrade() -> None:
    op.drop_table("platform_extension_catalog_entries")
