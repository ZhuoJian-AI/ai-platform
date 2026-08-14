"""ontology_folders + ontology_files（本体文件化）

将本体由 JSONB entities/relations 图结构改造为 Markdown 文件 + 文件夹存储（镜像工作空间文件模型）。
文件夹/文件均按 (organization_id, scope_type, scope_id) 直接作用域化，path 为相对作用域根的 POSIX 路径，
嵌套靠路径段表达。旧 ``ontologies`` 表暂保留 dormant，agent 运行时改读 ontology_files.content。

Revision ID: 0018_ontology_files
Revises: 0017_rag_folders_doc_path
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "0018_ontology_files"
down_revision = "0017_rag_folders_doc_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="organization"),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "scope_type", "scope_id", "path", name="uq_ontology_folder_path"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_ontology_folders_org_scope", "ontology_folders", ["organization_id", "scope_type", "scope_id"])

    op.create_table(
        "ontology_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="organization"),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "scope_type", "scope_id", "path", name="uq_ontology_file_path"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_ontology_files_org_scope", "ontology_files", ["organization_id", "scope_type", "scope_id"])


def downgrade() -> None:
    op.drop_index("ix_ontology_files_org_scope", table_name="ontology_files")
    op.drop_table("ontology_files")
    op.drop_index("ix_ontology_folders_org_scope", table_name="ontology_folders")
    op.drop_table("ontology_folders")
