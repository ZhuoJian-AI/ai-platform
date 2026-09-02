"""Add durable workspace fallback preview jobs.

Revision ID: 0056_workspace_preview_jobs
Revises: 0055_org_slug_aliases
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0056_workspace_preview_jobs"
down_revision = "0055_org_slug_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_preview_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversion_type", sa.String(length=32), nullable=False, server_default="pdf"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("output_ref", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_file_id"], ["workspace_files.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["file_version_id"], ["workspace_file_versions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "file_version_id", "conversion_type", name="uq_workspace_preview_version_type"
        ),
    )
    for column in (
        "workspace_file_id", "file_version_id", "status", "next_attempt_at",
        "lease_expires_at",
    ):
        op.create_index(
            f"ix_workspace_preview_jobs_{column}", "workspace_preview_jobs", [column]
        )


def downgrade() -> None:
    op.drop_table("workspace_preview_jobs")
