"""Direct ECS publisher runtimes and release registration.

Revision ID: 0048_ecs_publisher_runtime
Revises: 0047_module_deployment_control
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0048_ecs_publisher_runtime"
down_revision = "0047_module_deployment_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ecs_runtimes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_key", sa.String(80), nullable=False),
        sa.Column("enterprise_key", sa.String(80), nullable=False),
        sa.Column("environment", sa.String(40), nullable=False, server_default="staging"),
        sa.Column("domain_suffix", sa.String(255), nullable=False),
        sa.Column("public_address", sa.String(255), nullable=True),
        sa.Column("credential_prefix", sa.String(24), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("credential_rotated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "runtime_key", name="uq_ecs_runtime_org_key"),
        sa.UniqueConstraint("credential_prefix", name="uq_ecs_runtime_credential_prefix"),
        sa.UniqueConstraint("credential_hash", name="uq_ecs_runtime_credential_hash"),
    )
    op.create_index("ix_ecs_runtimes_organization_id", "ecs_runtimes", ["organization_id"])

    op.create_table(
        "ecs_module_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("application_slug", sa.String(80), nullable=False),
        sa.Column("application_name", sa.String(255), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("requested_commit", sa.String(64), nullable=False),
        sa.Column("last_success_commit", sa.String(64), nullable=True),
        sa.Column("image_ref", sa.Text(), nullable=True),
        sa.Column("contract_revision", sa.String(20), nullable=True),
        sa.Column("manifest_digest", sa.String(64), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="verifying"),
        sa.Column(
            "release_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('verifying','healthy','failed')", name="ck_ecs_module_release_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["runtime_id"], ["ecs_runtimes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "application_slug", name="uq_ecs_module_release_org_slug"),
    )
    op.create_index("ix_ecs_module_releases_organization_id", "ecs_module_releases", ["organization_id"])
    op.create_index("ix_ecs_module_releases_runtime_id", "ecs_module_releases", ["runtime_id"])
    op.create_index("ix_ecs_module_releases_application_id", "ecs_module_releases", ["application_id"])


def downgrade() -> None:
    op.drop_table("ecs_module_releases")
    op.drop_table("ecs_runtimes")
