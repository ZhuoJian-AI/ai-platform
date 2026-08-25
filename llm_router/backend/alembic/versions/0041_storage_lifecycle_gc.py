"""Skill OSS packages and unified 30-day storage lifecycle.

Revision ID: 0041_storage_lifecycle_gc
Revises: 0040_extension_catalog
Create Date: 2026-08-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0041_storage_lifecycle_gc"
down_revision = "0040_extension_catalog"
branch_labels = None
depends_on = None


_PURGE_TABLES = (
    "workspaces",
    "workspace_folders",
    "skill_folders",
    "skill_files",
    "rag_collections",
    "rag_documents",
    "rag_folders",
    "ontologies",
    "ontology_folders",
    "ontology_files",
)


def upgrade() -> None:
    op.alter_column("skill_versions", "archive", existing_type=sa.LargeBinary(), nullable=True)
    op.add_column("skill_versions", sa.Column("archive_ref", sa.Text(), nullable=True))
    op.add_column("skill_versions", sa.Column("archive_size", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column(
        "skill_versions",
        sa.Column("storage_status", sa.String(20), nullable=False, server_default="inline"),
    )
    op.add_column("skill_versions", sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column("skill_versions", sa.Column("archive_purged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_skill_versions_storage_status", "skill_versions", ["storage_status"])
    op.create_index("ix_skill_versions_purge_after", "skill_versions", ["purge_after"])
    op.execute("UPDATE skill_versions SET archive_size = octet_length(archive) WHERE archive IS NOT NULL")

    for table in _PURGE_TABLES:
        op.add_column(table, sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_purge_after", table, ["purge_after"])
        op.execute(
            f"UPDATE {table} SET purge_after = deleted_at + interval '30 days' "
            "WHERE deleted_at IS NOT NULL AND purge_after IS NULL"
        )

    # 0038 introduced purge_after on workspace files, but several historical
    # delete paths did not populate it. Backfill before the hourly worker runs.
    op.execute(
        "UPDATE workspace_files SET purge_after = deleted_at + interval '30 days' "
        "WHERE deleted_at IS NOT NULL AND purge_after IS NULL"
    )
    op.execute(
        "UPDATE skill_versions v SET purge_after = f.deleted_at + interval '30 days' "
        "FROM skill_folders f WHERE v.skill_folder_id = f.id "
        "AND f.deleted_at IS NOT NULL AND v.purge_after IS NULL"
    )


def downgrade() -> None:
    for table in reversed(_PURGE_TABLES):
        op.drop_index(f"ix_{table}_purge_after", table_name=table)
        op.drop_column(table, "purge_after")
    op.drop_index("ix_skill_versions_purge_after", table_name="skill_versions")
    op.drop_index("ix_skill_versions_storage_status", table_name="skill_versions")
    op.drop_column("skill_versions", "archive_purged_at")
    op.drop_column("skill_versions", "purge_after")
    op.drop_column("skill_versions", "storage_status")
    op.drop_column("skill_versions", "archive_size")
    op.drop_column("skill_versions", "archive_ref")
    # Downgrade cannot safely make archive NOT NULL after OSS-only packages
    # have existed. Keep it nullable to avoid destructive data fabrication.
