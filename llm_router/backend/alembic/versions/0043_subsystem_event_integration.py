"""Subsystem integration registry, event receipts and cross-department work items.

Revision ID: 0043_subsystem_event_integration
Revises: 0042_enterprise_applications
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0043_subsystem_event_integration"
down_revision = "0042_enterprise_applications"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.add_column(
        "enterprise_application_grants",
        sa.Column("module_keys", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )

    op.create_table(
        "enterprise_application_integrations",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_url", sa.Text(), nullable=False),
        sa.Column("events_url", sa.Text(), nullable=True),
        sa.Column("auth_token_encrypted", sa.Text(), nullable=True),
        sa.Column("protocol_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cursor_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="ready"),
        sa.Column("last_manifest_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "sync_status IN ('unconfigured','ready','syncing','healthy','error')",
            name="ck_enterprise_application_integration_status",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", name="uq_enterprise_application_integration_app"),
    )
    op.create_index(
        "ix_enterprise_application_integrations_application_id",
        "enterprise_application_integrations",
        ["application_id"],
    )
    op.create_index(
        "ix_enterprise_application_integrations_organization_id",
        "enterprise_application_integrations",
        ["organization_id"],
    )

    op.create_table(
        "enterprise_application_events",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("source_sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("module_key", sa.String(120), nullable=True),
        sa.Column("entity_type", sa.String(120), nullable=True),
        sa.Column("entity_id", sa.String(200), nullable=True),
        sa.Column("action", sa.String(80), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "event_id", name="uq_enterprise_application_event_id"),
        sa.UniqueConstraint("application_id", "source_sequence", name="uq_enterprise_application_event_sequence"),
    )
    op.create_index(
        "ix_enterprise_application_events_application_id", "enterprise_application_events", ["application_id"]
    )
    op.create_index(
        "ix_enterprise_application_events_organization_id", "enterprise_application_events", ["organization_id"]
    )
    op.create_index("ix_enterprise_application_events_event_type", "enterprise_application_events", ["event_type"])
    op.create_index("ix_enterprise_application_events_module_key", "enterprise_application_events", ["module_key"])

    op.create_table(
        "enterprise_application_event_routes",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("module_key", sa.String(120), nullable=True),
        sa.Column("target_scope_type", sa.String(20), nullable=False),
        sa.Column("target_scope_id", sa.String(36), nullable=True),
        sa.Column("target_module_key", sa.String(120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_scope_type IN ('organization','department','team','user')",
            name="ck_enterprise_application_event_route_scope_type",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enterprise_application_event_routes_application_id",
        "enterprise_application_event_routes",
        ["application_id"],
    )
    op.create_index(
        "ix_enterprise_application_event_routes_organization_id",
        "enterprise_application_event_routes",
        ["organization_id"],
    )

    op.create_table(
        "cross_department_work_items",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("target_scope_type", sa.String(20), nullable=False),
        sa.Column("target_scope_id", sa.String(36), nullable=True),
        sa.Column("target_module_key", sa.String(120), nullable=True),
        sa.Column("source_context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
        sa.CheckConstraint("status IN ('open','done')", name="ck_cross_department_work_item_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_id"], ["enterprise_application_event_routes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_id", "source_event_id", name="uq_cross_department_work_item_route_event"),
    )
    op.create_index(
        "ix_cross_department_work_items_organization_id", "cross_department_work_items", ["organization_id"]
    )
    op.create_index(
        "ix_cross_department_work_items_source_application_id", "cross_department_work_items", ["source_application_id"]
    )
    op.create_index("ix_cross_department_work_items_route_id", "cross_department_work_items", ["route_id"])
    op.create_index(
        "ix_cross_department_work_items_target_scope_id", "cross_department_work_items", ["target_scope_id"]
    )


def downgrade() -> None:
    op.drop_table("cross_department_work_items")
    op.drop_table("enterprise_application_event_routes")
    op.drop_table("enterprise_application_events")
    op.drop_table("enterprise_application_integrations")
    op.drop_column("enterprise_application_grants", "module_keys")
