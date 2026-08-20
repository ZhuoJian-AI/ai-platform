"""workspace governance, immutable versions and direct upload sessions

Revision ID: 0038_workspace_governance
Revises: 0037_model_gateway
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0038_workspace_governance"
down_revision = "0037_model_gateway"
branch_labels = None
depends_on = None


def _uuid() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.add_column("workspace_files", sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("workspace_files", sa.Column("deleted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("workspace_files", sa.Column("deleted_by_admin_id", sa.BigInteger(), nullable=True))
    op.add_column("workspace_files", sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workspace_files", sa.Column("parse_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("workspace_files", sa.Column("parse_locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workspace_files", sa.Column("parse_locked_by", sa.String(100), nullable=True))
    op.create_foreign_key(
        "fk_wsfile_creator", "workspace_files", "users",
        ["created_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_wsfile_deleted_user", "workspace_files", "users",
        ["deleted_by_user_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_wsfile_deleted_admin", "workspace_files", "admins",
        ["deleted_by_admin_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_workspace_files_created_by_user_id", "workspace_files", ["created_by_user_id"])
    op.create_index("ix_workspace_files_purge_after", "workspace_files", ["purge_after"])

    op.create_table(
        "workspace_file_versions",
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("content_ref", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.String(20), nullable=False, server_default="unparsed"),
        sa.Column("parse_kind", sa.String(20), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        _uuid(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workspace_file_id", "version_no", name="uq_wsfile_version"),
    )
    op.create_index("ix_workspace_file_versions_workspace_file_id", "workspace_file_versions", ["workspace_file_id"])
    op.add_column("workspace_files", sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_wsfile_current_version", "workspace_files", "workspace_file_versions",
        ["current_version_id"], ["id"], ondelete="SET NULL",
    )
    op.execute("""
        INSERT INTO workspace_file_versions (
            workspace_file_id, version_no, size, content_hash, content_ref, content,
            extracted_text, parse_status, parse_kind, parse_error, metadata,
            id, created_at, updated_at
        )
        SELECT id, 1, size, content_hash, content_ref, content, extracted_text,
               parse_status, parse_kind, parse_error, metadata,
               gen_random_uuid(), created_at, updated_at
        FROM workspace_files
    """)
    op.execute("""
        UPDATE workspace_files f SET current_version_id = v.id
        FROM workspace_file_versions v
        WHERE v.workspace_file_id = f.id AND v.version_no = 1
    """)

    op.create_table(
        "workspace_upload_sessions",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("content_ref", sa.Text(), nullable=True),
        sa.Column("upload_url", sa.Text(), nullable=True),
        sa.Column("upload_headers", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        _uuid(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "(user_id IS NOT NULL) <> (admin_id IS NOT NULL)",
            name="ck_workspace_upload_session_one_actor",
        ),
    )
    for column in ("organization_id", "workspace_id", "user_id", "admin_id", "status", "expires_at"):
        op.create_index(f"ix_workspace_upload_sessions_{column}", "workspace_upload_sessions", [column])

    op.create_table(
        "workspace_audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["workspace_file_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_admin_id"], ["admins.id"], ondelete="SET NULL"),
    )
    for column in ("organization_id", "workspace_id", "workspace_file_id", "action"):
        op.create_index(f"ix_workspace_audit_events_{column}", "workspace_audit_events", [column])

    op.create_table(
        "workspace_share_links",
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        _uuid(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["workspace_file_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_share_token_hash"),
    )
    for column in ("workspace_file_id", "version_id", "token_hash", "expires_at"):
        op.create_index(f"ix_workspace_share_links_{column}", "workspace_share_links", [column])


def downgrade() -> None:
    op.drop_table("workspace_share_links")
    op.drop_table("workspace_audit_events")
    op.drop_table("workspace_upload_sessions")
    op.drop_constraint("fk_wsfile_current_version", "workspace_files", type_="foreignkey")
    op.drop_column("workspace_files", "current_version_id")
    op.drop_table("workspace_file_versions")
    op.drop_index("ix_workspace_files_purge_after", table_name="workspace_files")
    op.drop_index("ix_workspace_files_created_by_user_id", table_name="workspace_files")
    op.drop_constraint("fk_wsfile_deleted_admin", "workspace_files", type_="foreignkey")
    op.drop_constraint("fk_wsfile_deleted_user", "workspace_files", type_="foreignkey")
    op.drop_constraint("fk_wsfile_creator", "workspace_files", type_="foreignkey")
    for column in (
        "parse_locked_by", "parse_locked_at", "parse_attempts", "purge_after",
        "deleted_by_admin_id", "deleted_by_user_id", "created_by_user_id",
    ):
        op.drop_column("workspace_files", column)
