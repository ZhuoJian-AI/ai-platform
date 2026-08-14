"""workspace_folders table

工作空间文件夹实体：与 workspace_files 平行，path 为相对 workspace root
的 POSIX 路径，嵌套靠路径段表达。支持空文件夹与按文件夹为单位的级联删除。

Revision ID: 0016_workspace_folders
Revises: 0015_drop_viewer_role
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0016_workspace_folders"
down_revision = "0015_drop_viewer_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "path", name="uq_wsfolder_path"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workspace_folders_workspace_id", "workspace_folders", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_folders_workspace_id", table_name="workspace_folders")
    op.drop_table("workspace_folders")
