"""Page-scoped authorization and cross-subsystem event deliveries.

Revision ID: 0045_subsystem_pages_event_delivery
Revises: 0044_subsystem_protocol_v2
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0045_subsystem_pages_event_delivery"
down_revision = "0044_subsystem_protocol_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_enterprise_application_tool_binding_operation",
        "enterprise_application_tool_bindings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_tool_binding_operation",
        "enterprise_application_tool_bindings",
        "operation IN ('query','create','update','delete','export','approve')",
    )
    op.drop_constraint(
        "ck_enterprise_application_action_operation",
        "enterprise_application_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_action_operation",
        "enterprise_application_actions",
        "operation IN ('query','create','update','delete','export','approve')",
    )
    op.add_column(
        "enterprise_application_event_routes",
        sa.Column("target_application_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_enterprise_event_route_target_application",
        "enterprise_application_event_routes",
        "enterprise_applications",
        ["target_application_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_enterprise_application_event_routes_target_application_id",
        "enterprise_application_event_routes",
        ["target_application_id"],
    )
    op.create_table(
        "enterprise_application_event_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','delivering','delivered','failed')",
            name="ck_enterprise_event_delivery_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_id"], ["enterprise_application_event_routes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["enterprise_application_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", name="uq_enterprise_application_event_deliveries_delivery_id"),
        sa.UniqueConstraint("route_id", "source_event_id", name="uq_enterprise_event_delivery_route_event"),
    )
    for column in ("organization_id", "route_id", "source_event_id", "target_application_id"):
        op.create_index(
            f"ix_enterprise_application_event_deliveries_{column}",
            "enterprise_application_event_deliveries",
            [column],
        )


def downgrade() -> None:
    op.drop_table("enterprise_application_event_deliveries")
    op.drop_index(
        "ix_enterprise_application_event_routes_target_application_id",
        table_name="enterprise_application_event_routes",
    )
    op.drop_constraint(
        "fk_enterprise_event_route_target_application",
        "enterprise_application_event_routes",
        type_="foreignkey",
    )
    op.drop_column("enterprise_application_event_routes", "target_application_id")
    op.drop_constraint(
        "ck_enterprise_application_action_operation",
        "enterprise_application_actions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_action_operation",
        "enterprise_application_actions",
        "operation IN ('query','create','update','delete','export')",
    )
    op.drop_constraint(
        "ck_enterprise_application_tool_binding_operation",
        "enterprise_application_tool_bindings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_tool_binding_operation",
        "enterprise_application_tool_bindings",
        "operation IN ('query','create','update','delete','export')",
    )
