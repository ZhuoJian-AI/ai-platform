"""Tenant business applications, scoped grants and tool bindings.

Revision ID: 0042_enterprise_applications
Revises: 0041_storage_lifecycle_gc
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0042_enterprise_applications"
down_revision = "0041_storage_lifecycle_gc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_applications",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon_url", sa.Text(), nullable=True),
        sa.Column("entry_url", sa.Text(), nullable=False),
        sa.Column("display_mode", sa.String(20), nullable=False, server_default="embedded"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assistant_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assistant_prompt", sa.Text(), nullable=True),
        sa.Column("assistant_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("health_status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("display_mode IN ('embedded','external')", name="ck_enterprise_application_display_mode"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_enterprise_application_org_slug"),
    )
    op.create_index("ix_enterprise_applications_organization_id", "enterprise_applications", ["organization_id"])
    op.create_index(
        "ix_enterprise_applications_active_order",
        "enterprise_applications",
        ["organization_id", "is_active", "sort_order"],
    )

    op.create_table(
        "enterprise_application_grants",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('organization','department','team','user')",
            name="ck_enterprise_application_grant_scope_type",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "scope_type", "scope_id", name="uq_enterprise_application_grant_scope"),
    )
    op.create_index(
        "ix_enterprise_application_grants_application_id", "enterprise_application_grants", ["application_id"]
    )
    op.create_index(
        "ix_enterprise_application_grants_organization_id", "enterprise_application_grants", ["organization_id"]
    )
    op.create_index("ix_enterprise_application_grants_scope_id", "enterprise_application_grants", ["scope_id"])
    op.create_index(
        "ix_enterprise_application_grants_scope",
        "enterprise_application_grants",
        ["organization_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "uq_enterprise_application_grant_org_scope",
        "enterprise_application_grants",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text(
            "scope_type = 'organization' AND scope_id IS NULL AND deleted_at IS NULL"
        ),
    )

    op.create_table(
        "enterprise_application_tool_bindings",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_type IN ('tool_endpoint','data_interface','skill_folder')",
            name="ck_enterprise_application_tool_binding_target_type",
        ),
        sa.CheckConstraint(
            "operation IN ('query','create','update','delete','export')",
            name="ck_enterprise_application_tool_binding_operation",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id", "target_type", "target_id", "operation", name="uq_enterprise_application_tool_binding"
        ),
    )
    op.create_index(
        "ix_enterprise_application_tool_bindings_application_id",
        "enterprise_application_tool_bindings",
        ["application_id"],
    )
    op.create_index(
        "ix_enterprise_application_tool_bindings_organization_id",
        "enterprise_application_tool_bindings",
        ["organization_id"],
    )
    op.create_index(
        "ix_enterprise_application_tool_bindings_target_id", "enterprise_application_tool_bindings", ["target_id"]
    )
    op.create_index(
        "ix_enterprise_application_tool_bindings_target",
        "enterprise_application_tool_bindings",
        ["organization_id", "target_type", "target_id"],
    )


def downgrade() -> None:
    op.drop_table("enterprise_application_tool_bindings")
    op.drop_table("enterprise_application_grants")
    op.drop_table("enterprise_applications")
