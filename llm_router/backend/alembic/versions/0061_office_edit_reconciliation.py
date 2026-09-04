"""Add durable WebOffice edit reconciliation and file event outbox.

Revision ID: 0061_office_edit_reconciliation
Revises: 0060_wsfile_active_path
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0061_office_edit_reconciliation"
down_revision = "0060_wsfile_active_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_file_versions",
        sa.Column("storage_version_id", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "workspace_file_versions",
        sa.Column("storage_etag", sa.String(length=256), nullable=True),
    )

    op.create_table(
        "office_edit_rooms",
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_file_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_content_ref", sa.Text(), nullable=False),
        sa.Column("source_storage_version_id", sa.String(length=1024), nullable=True),
        sa.Column("source_revision", sa.String(length=64), nullable=True),
        sa.Column("source_etag", sa.String(length=256), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("client_open_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_file_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_version_id"], ["workspace_file_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["final_file_version_id"], ["workspace_file_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_file_id", "actor_type", "actor_id", "client_open_id",
            name="uq_office_edit_room_client_open",
        ),
    )
    for column in ("workspace_file_id", "source_file_version_id", "status", "expires_at"):
        op.create_index(f"ix_office_edit_rooms_{column}", "office_edit_rooms", [column])

    op.create_table(
        "office_save_events",
        sa.Column("gateway_event_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("office_edit_room_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repository_id", sa.String(length=128), nullable=False),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("notified_storage_version_id", sa.String(length=1024), nullable=True),
        sa.Column("notified_etag", sa.String(length=256), nullable=False),
        sa.Column("notified_size", sa.BigInteger(), nullable=False),
        sa.Column("notified_content_type", sa.String(length=255), nullable=False),
        sa.Column("notified_content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_user_id", sa.String(length=64), nullable=False),
        sa.Column("source_revision", sa.String(length=64), nullable=False),
        sa.Column("notified_integrity_algorithm", sa.String(length=32), nullable=False),
        sa.Column("notified_integrity_value", sa.String(length=128), nullable=False),
        sa.Column("imm_version", sa.String(length=128), nullable=True),
        sa.Column("event_time", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("resolved_storage_version_id", sa.String(length=1024), nullable=True),
        sa.Column("resolved_file_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["office_edit_room_id"], ["office_edit_rooms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_file_version_id"], ["workspace_file_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gateway_event_id"),
    )
    for column in (
        "gateway_event_id", "workspace_file_id", "office_edit_room_id", "status", "next_attempt_at",
    ):
        op.create_index(f"ix_office_save_events_{column}", "office_save_events", [column])

    op.create_table(
        "workspace_file_event_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["workspace_file_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "workspace_id", "workspace_file_id", "event_type", "created_at"):
        op.create_index(
            f"ix_workspace_file_event_outbox_{column}", "workspace_file_event_outbox", [column]
        )


def downgrade() -> None:
    op.drop_table("workspace_file_event_outbox")
    op.drop_table("office_save_events")
    op.drop_table("office_edit_rooms")
    op.drop_column("workspace_file_versions", "storage_etag")
    op.drop_column("workspace_file_versions", "storage_version_id")
