"""Add durable task file context references.

Revision ID: 0062_task_file_refs
Revises: 0061_office_edit_reconciliation
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0062_task_file_refs"
down_revision = "0061_office_edit_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_file_refs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="turn"),
        sa.Column("follow_latest", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="message"),
        sa.Column("workspace_name", sa.String(length=255), nullable=True),
        sa.Column("canonical_path", sa.String(length=1400), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["workspace_file_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "workspace_file_id", name="uq_task_file_ref"),
    )
    op.create_index("ix_task_file_refs_task_id", "task_file_refs", ["task_id"])
    op.create_index("ix_task_file_refs_workspace_file_id", "task_file_refs", ["workspace_file_id"])
    op.create_index("ix_task_file_refs_scope", "task_file_refs", ["scope"])


def downgrade() -> None:
    op.drop_table("task_file_refs")
