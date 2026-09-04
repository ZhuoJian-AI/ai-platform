"""Add tenant-scoped MCP OAuth records and user auth epoch.

Revision ID: 0065_mcp_oauth
Revises: 0064_admin_roles
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0065_mcp_oauth"
down_revision = "0064_admin_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing verifiers continue to work; erase legacy reversible copies so a
    # database or admin-console compromise cannot recover bearer credentials.
    op.execute("UPDATE api_keys SET key_encrypted = '' WHERE key_encrypted <> ''")
    # Old exported skills packs embedded bearer keys with no user/auth-epoch
    # binding. OAuth replaces that channel, so revoke those credentials during
    # the same migration instead of leaving a fictional compatibility window.
    op.execute(
        """
        UPDATE api_keys
        SET is_active = false, revoked_at = now(), expires_at = now()
        WHERE key_name LIKE 'skills-pack:%' AND is_active = true
        """
    )
    op.add_column(
        "users",
        sa.Column("auth_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("admins", sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "admins",
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "admins",
        sa.Column(
            "mfa_recovery_code_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("admins", sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("admins", sa.Column("mfa_last_totp_counter", sa.Integer(), nullable=True))

    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("grant_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(length=32), nullable=False),
        sa.Column("registration_source_hash", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_index(
        "ix_oauth_clients_registration_source_hash",
        "oauth_clients",
        ["registration_source_hash"],
    )
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("issued_auth_epoch", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_oauth_authorization_codes_client_id", "oauth_authorization_codes", ["client_id"])
    op.create_index("ix_oauth_authorization_codes_user_id", "oauth_authorization_codes", ["user_id"])
    op.create_index("ix_oauth_authorization_codes_organization_id", "oauth_authorization_codes", ["organization_id"])

    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_hash", sa.String(length=64), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_oauth_refresh_tokens_family", "oauth_refresh_tokens", ["family_id"])
    op.create_index("ix_oauth_refresh_tokens_client_id", "oauth_refresh_tokens", ["client_id"])
    op.create_index("ix_oauth_refresh_tokens_user_id", "oauth_refresh_tokens", ["user_id"])
    op.create_index("ix_oauth_refresh_tokens_organization_id", "oauth_refresh_tokens", ["organization_id"])


def downgrade() -> None:
    op.drop_table("oauth_refresh_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_clients")
    op.drop_column("admins", "mfa_last_totp_counter")
    op.drop_column("admins", "mfa_verified_at")
    op.drop_column("admins", "mfa_recovery_code_hashes")
    op.drop_column("admins", "mfa_enabled")
    op.drop_column("admins", "mfa_secret_encrypted")
    op.drop_column("users", "auth_epoch")
