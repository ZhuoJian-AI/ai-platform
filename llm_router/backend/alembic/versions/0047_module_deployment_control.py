"""Tenant-scoped Coolify module deployment control.

Revision ID: 0047_module_deployment_control
Revises: 0046_user_multi_departments
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0047_module_deployment_control"
down_revision = "0046_user_multi_departments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_deployment_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runtime_key", sa.String(80), nullable=False),
        sa.Column("server_uuid", sa.String(120), nullable=False),
        sa.Column("project_uuid", sa.String(120), nullable=False),
        sa.Column("environment_name", sa.String(120), nullable=False, server_default="production"),
        sa.Column("environment_uuid", sa.String(120), nullable=True),
        sa.Column("destination_uuid", sa.String(120), nullable=True),
        sa.Column("github_app_uuid", sa.String(120), nullable=False),
        sa.Column("domain_suffix", sa.String(255), nullable=False),
        sa.Column("use_build_server", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "runtime_key", name="uq_module_deployment_profile_org_runtime"
        ),
    )
    op.create_index("ix_module_deployment_profiles_org", "module_deployment_profiles", ["organization_id"])
    op.create_index(
        "uq_module_deployment_profile_org_default",
        "module_deployment_profiles",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )
    op.create_table(
        "module_deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deployment_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module_slug", sa.String(80), nullable=False),
        sa.Column("module_name", sa.String(255), nullable=False),
        sa.Column("repository_name", sa.String(255), nullable=False),
        sa.Column("coolify_application_uuid", sa.String(120), nullable=False),
        sa.Column("entry_url", sa.Text(), nullable=False),
        sa.Column("integration_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("session_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("requested_commit", sa.String(64), nullable=False),
        sa.Column("last_success_commit", sa.String(64), nullable=True),
        sa.Column("deployment_uuid", sa.String(120), nullable=True),
        sa.Column("rollback_deployment_uuid", sa.String(120), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("failure_stage", sa.String(40), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["deployment_profile_id"], ["module_deployment_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["application_id"], ["enterprise_applications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "module_slug", name="uq_module_deployment_org_slug"),
    )
    op.create_index("ix_module_deployments_org", "module_deployments", ["organization_id"])
    op.create_index(
        "ix_module_deployments_profile", "module_deployments", ["deployment_profile_id"]
    )
    op.create_index("ix_module_deployments_application", "module_deployments", ["application_id"])


def downgrade() -> None:
    op.drop_table("module_deployments")
    op.drop_table("module_deployment_profiles")
