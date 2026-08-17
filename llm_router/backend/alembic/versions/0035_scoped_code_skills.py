"""scoped managers and immutable executable skill versions

Revision ID: 0035_scoped_code_skills
Revises: 0034_workspace_file_parsing
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0035_scoped_code_skills"
down_revision = "0034_workspace_file_parsing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scope_manager_assignments",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope_type IN ('department','team')", name="ck_scope_manager_type"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "scope_type", "scope_id", name="uq_scope_manager_assignment"),
    )
    op.create_index("ix_scope_manager_org", "scope_manager_assignments", ["organization_id"])
    op.create_index("ix_scope_manager_user", "scope_manager_assignments", ["user_id"])
    op.create_index("ix_scope_manager_scope", "scope_manager_assignments", ["scope_id"])

    op.create_table(
        "skill_versions",
        sa.Column("skill_folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("package_hash", sa.String(64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("archive", sa.LargeBinary(), nullable=False),
        sa.Column("runtime", sa.String(20), nullable=False, server_default="prompt"),
        sa.Column("entrypoint", sa.String(1024), nullable=True),
        sa.Column("is_executable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("install_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("install_error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["skill_folder_id"], ["skill_folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_folder_id", "version_no", name="uq_skill_version_number"),
        sa.UniqueConstraint("skill_folder_id", "package_hash", name="uq_skill_version_hash"),
    )
    op.create_index("ix_skill_versions_folder", "skill_versions", ["skill_folder_id"])
    op.create_index("ix_skill_versions_status", "skill_versions", ["install_status"])
    op.add_column(
        "skill_folders",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("skill_folders", sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_skill_folder_active_version", "skill_folders", "skill_versions",
        ["active_version_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_skill_folders_active_version", "skill_folders", ["active_version_id"])

    op.create_table(
        "skill_executions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_file_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("output_file_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_folder_id"], ["skill_folders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["skill_version_id"], ["skill_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    execution_indexes = (
        "organization_id", "user_id", "task_id", "agent_id",
        "skill_folder_id", "skill_version_id", "status",
    )
    for column in execution_indexes:
        op.create_index(f"ix_skill_executions_{column}", "skill_executions", [column])

    op.drop_constraint("uq_skill_folder_scope_slug", "skill_folders", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_skill_folder_scope_slug_live ON skill_folders "
        "(organization_id, scope_type, COALESCE(scope_id, ''), slug) WHERE deleted_at IS NULL"
    )
    op.drop_constraint("uq_skill_file_path", "skill_files", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_skill_file_path_live ON skill_files "
        "(skill_folder_id, path) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_skill_file_path_live")
    op.create_unique_constraint("uq_skill_file_path", "skill_files", ["skill_folder_id", "path"])
    op.execute("DROP INDEX IF EXISTS uq_skill_folder_scope_slug_live")
    op.create_unique_constraint(
        "uq_skill_folder_scope_slug", "skill_folders", ["organization_id", "scope_type", "scope_id", "slug"]
    )
    op.drop_table("skill_executions")
    op.drop_index("ix_skill_folders_active_version", table_name="skill_folders")
    op.drop_constraint("fk_skill_folder_active_version", "skill_folders", type_="foreignkey")
    op.drop_column("skill_folders", "active_version_id")
    op.drop_column("skill_folders", "is_active")
    op.drop_table("skill_versions")
    op.drop_table("scope_manager_assignments")
