"""Add optimistic/idempotent workspace file mutation metadata.

Revision ID: 0059_workspace_file_mutation
Revises: 0058_protocol_provider_vendors
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0059_workspace_file_mutation"
down_revision = "0058_protocol_provider_vendors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_file_versions",
        sa.Column("mutation_idempotency_key", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "workspace_file_versions",
        sa.Column("mutation_request_hash", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_wsfile_version_mutation_key",
        "workspace_file_versions",
        ["workspace_file_id", "mutation_idempotency_key"],
    )
    op.create_table(
        "file_mutations",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column(
            "result", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_file_id"], ["workspace_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["base_version_id"], ["workspace_file_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["result_file_id"], ["workspace_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["result_version_id"], ["workspace_file_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "actor_type", "actor_id", "idempotency_key",
            name="uq_file_mutation_actor_key",
        ),
    )
    for column in ("organization_id", "workspace_id", "workspace_file_id", "status"):
        op.create_index(f"ix_file_mutations_{column}", "file_mutations", [column])


def downgrade() -> None:
    op.drop_table("file_mutations")
    op.drop_constraint(
        "uq_wsfile_version_mutation_key",
        "workspace_file_versions",
        type_="unique",
    )
    op.drop_column("workspace_file_versions", "mutation_request_hash")
    op.drop_column("workspace_file_versions", "mutation_idempotency_key")
