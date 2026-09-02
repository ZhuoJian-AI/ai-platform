"""Preserve historical organization slugs as login aliases.

Revision ID: 0055_org_slug_aliases
Revises: 0054_auth_cleanup
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0055_org_slug_aliases"
down_revision = "0054_auth_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_slug_aliases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("slug", name="uq_organization_slug_aliases_slug"),
    )
    op.create_index(
        "ix_organization_slug_aliases_organization_id",
        "organization_slug_aliases",
        ["organization_id"],
    )

    # Historical compatibility for the existing 爱法贝 tenant. The guard keeps
    # the migration safe on installations where either slug belongs elsewhere.
    op.execute(sa.text("""
        INSERT INTO organization_slug_aliases (id, organization_id, slug, created_at, updated_at)
        SELECT gen_random_uuid(), target.id, 'aifabei', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM organizations AS target
        WHERE target.slug = 'alphabet'
          AND target.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM organizations AS current_owner
              WHERE current_owner.slug = 'aifabei'
                AND current_owner.deleted_at IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM organization_slug_aliases AS existing_alias
              WHERE existing_alias.slug = 'aifabei'
          )
    """))


def downgrade() -> None:
    op.drop_index(
        "ix_organization_slug_aliases_organization_id",
        table_name="organization_slug_aliases",
    )
    op.drop_table("organization_slug_aliases")
