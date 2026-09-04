"""Separate subsystem credentials and add one-time SSO launch codes.

Revision ID: 0063_subsystem_credentials_sso
Revises: 0062_task_file_refs
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0063_subsystem_credentials_sso"
down_revision = "0062_task_file_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enterprise_application_integrations",
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column("sso_exchange_credential_prefix", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column("sso_exchange_credential_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column("action_signing_secret_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column("event_signing_secret_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column(
            "pending_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column(
            "manifest_diff",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column("manifest_review_status", sa.String(length=20), nullable=False, server_default="approved"),
    )
    op.add_column(
        "enterprise_application_integrations",
        sa.Column("pending_contract_revision", sa.String(length=20), nullable=True),
    )
    op.create_unique_constraint(
        "uq_enterprise_application_integration_sso_prefix",
        "enterprise_application_integrations",
        ["sso_exchange_credential_prefix"],
    )
    op.create_unique_constraint(
        "uq_enterprise_application_integration_sso_hash",
        "enterprise_application_integrations",
        ["sso_exchange_credential_hash"],
    )
    op.create_check_constraint(
        "ck_enterprise_application_integration_manifest_review",
        "enterprise_application_integrations",
        "manifest_review_status IN ('approved','pending','rejected')",
    )
    op.drop_constraint(
        "ck_enterprise_application_integration_status",
        "enterprise_application_integrations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_integration_status",
        "enterprise_application_integrations",
        "sync_status IN ('unconfigured','ready','syncing','healthy','pending_review','error')",
    )

    op.drop_constraint("ck_ecs_module_release_status", "ecs_module_releases", type_="check")
    op.create_check_constraint(
        "ck_ecs_module_release_status",
        "ecs_module_releases",
        "status IN ('verifying','pending_review','healthy','failed')",
    )

    op.create_table(
        "enterprise_application_sso_codes",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("module_key", sa.String(length=120), nullable=False),
        sa.Column("redirect_path", sa.Text(), nullable=False),
        sa.Column("session_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("launch_nonce", sa.String(length=128), nullable=False),
        sa.Column("claims_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_enterprise_application_sso_code_hash"),
    )
    op.create_index(
        "ix_enterprise_application_sso_codes_application_id",
        "enterprise_application_sso_codes",
        ["application_id"],
    )
    op.create_index(
        "ix_enterprise_application_sso_codes_organization_id",
        "enterprise_application_sso_codes",
        ["organization_id"],
    )
    op.create_index(
        "ix_enterprise_application_sso_codes_user_id",
        "enterprise_application_sso_codes",
        ["user_id"],
    )
    op.create_index(
        "ix_enterprise_application_sso_codes_expires_at",
        "enterprise_application_sso_codes",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("enterprise_application_sso_codes")

    # Normalize v2.5-only states before restoring the narrower legacy checks,
    # so an emergency rollback remains executable while reviews are pending.
    op.execute(
        sa.text(
            "UPDATE ecs_module_releases SET status = 'failed' "
            "WHERE status = 'pending_review'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE enterprise_application_integrations SET sync_status = 'error' "
            "WHERE sync_status = 'pending_review'"
        )
    )

    op.drop_constraint("ck_ecs_module_release_status", "ecs_module_releases", type_="check")
    op.create_check_constraint(
        "ck_ecs_module_release_status",
        "ecs_module_releases",
        "status IN ('verifying','healthy','failed')",
    )

    op.drop_constraint(
        "ck_enterprise_application_integration_status",
        "enterprise_application_integrations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_enterprise_application_integration_status",
        "enterprise_application_integrations",
        "sync_status IN ('unconfigured','ready','syncing','healthy','error')",
    )
    op.drop_constraint(
        "ck_enterprise_application_integration_manifest_review",
        "enterprise_application_integrations",
        type_="check",
    )
    op.drop_constraint(
        "uq_enterprise_application_integration_sso_hash",
        "enterprise_application_integrations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_enterprise_application_integration_sso_prefix",
        "enterprise_application_integrations",
        type_="unique",
    )
    for column in (
        "pending_contract_revision",
        "manifest_review_status",
        "manifest_diff",
        "pending_manifest",
        "event_signing_secret_encrypted",
        "action_signing_secret_encrypted",
        "sso_exchange_credential_hash",
        "sso_exchange_credential_prefix",
        "credential_version",
    ):
        op.drop_column("enterprise_application_integrations", column)
