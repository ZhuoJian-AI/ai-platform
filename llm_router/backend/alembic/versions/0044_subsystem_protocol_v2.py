"""Subsystem protocol v2 actions, confirmations and module-level grants.

Revision ID: 0044_subsystem_protocol_v2
Revises: 0043_subsystem_event_integration
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0044_subsystem_protocol_v2"
down_revision = "0043_subsystem_event_integration"
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
        sa.Column("module_access", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_table(
        "enterprise_application_actions",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_key", sa.String(120), nullable=False),
        sa.Column("action_key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("input_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.CheckConstraint(
            "operation IN ('query','create','update','delete','export')",
            name="ck_enterprise_application_action_operation",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "action_key", name="uq_enterprise_application_action_key"),
    )
    op.create_index(
        "ix_enterprise_application_actions_application_id", "enterprise_application_actions", ["application_id"]
    )
    op.create_index(
        "ix_enterprise_application_actions_organization_id", "enterprise_application_actions", ["organization_id"]
    )
    op.create_index("ix_enterprise_application_actions_module_key", "enterprise_application_actions", ["module_key"])

    op.create_table(
        "enterprise_application_action_requests",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(200), nullable=False),
        sa.Column("module_key", sa.String(120), nullable=False),
        sa.Column("params_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending','executing','completed','rejected','expired','failed')",
            name="ck_enterprise_application_action_request_status",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["enterprise_application_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            "user_id",
            "request_id",
            name="uq_enterprise_application_action_request",
        ),
    )
    op.create_index(
        "ix_enterprise_application_action_requests_application_id",
        "enterprise_application_action_requests",
        ["application_id"],
    )
    op.create_index(
        "ix_enterprise_application_action_requests_organization_id",
        "enterprise_application_action_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_enterprise_application_action_requests_action_id",
        "enterprise_application_action_requests",
        ["action_id"],
    )
    op.create_index(
        "ix_enterprise_application_action_requests_user_id",
        "enterprise_application_action_requests",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("enterprise_application_action_requests")
    op.drop_table("enterprise_application_actions")
    op.drop_column("enterprise_application_grants", "module_access")
