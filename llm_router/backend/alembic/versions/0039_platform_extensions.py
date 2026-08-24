"""platform extension sources, releases and events

Revision ID: 0039_platform_extensions
Revises: 0038_workspace_governance
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0039_platform_extensions"
down_revision = "0038_workspace_governance"
branch_labels = None
depends_on = None


def _uuid() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "platform_extension_sources",
        _uuid(),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("requested_version", sa.String(255), nullable=True),
        sa.Column("resolved_version", sa.String(255), nullable=True),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("artifact_ref", sa.Text(), nullable=True),
        sa.Column("artifact_sha256", sa.String(64), nullable=True),
        sa.Column("manifest", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("build_report", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("compatibility", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(30), nullable=False, server_default="importing"),
        sa.Column("review_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("imported_by_admin_id", sa.Integer(), nullable=False),
        sa.Column("approved_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["imported_by_admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
    )
    for column in ("source_type", "status", "review_status", "imported_by_admin_id"):
        op.create_index(f"ix_platform_extension_sources_{column}", "platform_extension_sources", [column])

    op.create_table(
        "platform_extension_releases",
        _uuid(),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("base_release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=False),
        sa.Column("published_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["base_release_id"], ["platform_extension_releases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["published_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("version_no"),
    )
    for column in ("version_no", "checksum", "status"):
        op.create_index(f"ix_platform_extension_releases_{column}", "platform_extension_releases", [column])
    op.create_index(
        "ix_platform_extension_releases_is_active",
        "platform_extension_releases",
        ["is_active"],
    )
    op.create_index(
        "uq_platform_extension_releases_one_active",
        "platform_extension_releases",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "platform_extension_release_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_admin_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="ok"),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["source_id"], ["platform_extension_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["release_id"], ["platform_extension_releases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_admin_id"], ["admins.id"], ondelete="SET NULL"),
    )
    for column in ("source_id", "release_id", "actor_admin_id", "event_type"):
        op.create_index(
            f"ix_platform_extension_release_events_{column}",
            "platform_extension_release_events",
            [column],
        )


def downgrade() -> None:
    op.drop_table("platform_extension_release_events")
    op.drop_table("platform_extension_releases")
    op.drop_table("platform_extension_sources")
