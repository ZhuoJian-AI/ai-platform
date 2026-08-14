"""skill_folders + skill_files（技能文件夹化）

技能改造成文件夹存储：一个技能即一个 ``skill_folders`` 行（节点作用域化），
文件夹内 ``skill.md``（含 ```skill JSON 块）定义 function-tool；``skill_files`` 存放文件夹内文件。
旧 ``skills`` 表（definition JSONB）dormant 保留；agent ``_build_tools`` 改读 skill.md manifest。

Revision ID: 0020_skill_folders
Revises: 0019_data_interfaces
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0020_skill_folders"
down_revision = "0019_data_interfaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="organization"),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "scope_type", "scope_id", "slug", name="uq_skill_folder_scope_slug"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_skill_folders_org_scope", "skill_folders", ["organization_id", "scope_type", "scope_id"])

    op.create_table(
        "skill_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("skill_folder_id", sa.UUID(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_folder_id", "path", name="uq_skill_file_path"),
        sa.ForeignKeyConstraint(["skill_folder_id"], ["skill_folders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_skill_files_folder", "skill_files", ["skill_folder_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_files_folder", table_name="skill_files")
    op.drop_table("skill_files")
    op.drop_index("ix_skill_folders_org_scope", table_name="skill_folders")
    op.drop_table("skill_folders")
