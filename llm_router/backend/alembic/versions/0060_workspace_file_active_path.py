"""Allow a new file identity after a same-path file is deleted.

Revision ID: 0060_wsfile_active_path
Revises: 0059_workspace_file_mutation
Create Date: 2026-09-03
"""

import sqlalchemy as sa

from alembic import op

revision = "0060_wsfile_active_path"
down_revision = "0059_workspace_file_mutation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_wsfile_path", "workspace_files", type_="unique")
    op.create_index(
        "uq_wsfile_path_active",
        "workspace_files",
        ["workspace_id", "path"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Never destroy historical logical files merely to satisfy an older
    # constraint.  Operators must resolve/re-home duplicate generations
    # explicitly before attempting this incompatible downgrade.
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM workspace_files
                GROUP BY workspace_id, path
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade 0060: duplicate workspace paths would require deleting history';
            END IF;
        END
        $$
    """))
    op.drop_index("uq_wsfile_path_active", table_name="workspace_files")
    op.create_unique_constraint(
        "uq_wsfile_path", "workspace_files", ["workspace_id", "path"],
    )
