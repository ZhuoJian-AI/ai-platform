"""Retire platform RAG and user-uploaded Skill products.

Revision ID: 0076_retire_rag_and_user_skills
Revises: 0075_retired_schema_contract
Create Date: 2026-09-09

This is an intentionally irreversible contract migration. Restore the paired
database snapshot and previous images if the coordinated release must be
rolled back.
"""

from alembic import op

revision = "0076_retire_rag_and_user_skills"
down_revision = "0075_retired_schema_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical task payloads are retained, but active task configuration may
    # no longer select retired resources.
    op.execute(
        """
        UPDATE tasks
        SET config = config
            - 'skill_ids'
            - 'invoked_skill_ids'
            - 'rag_collection_ids'
        WHERE config ?| ARRAY['skill_ids', 'invoked_skill_ids', 'rag_collection_ids']
        """
    )
    op.execute(
        """
        UPDATE organizations
        SET settings = settings - 'rag_ingest_defaults'
        WHERE settings ? 'rag_ingest_defaults'
        """
    )

    # Text personas no longer follow mutable RBAC role membership.  Preserve
    # every historical prompt without making it visible to a wider audience:
    # a role-scoped persona becomes personal to its valid creator.  Records
    # without a valid creator remain available to administrators for recovery,
    # but are disabled and moved to organization scope instead of being exposed.
    # Resolve a possible slug collision before changing the unique scope key.
    op.execute(
        """
        UPDATE agents AS legacy
        SET slug = LEFT(legacy.slug, 78)
            || '-legacy-'
            || LEFT(REPLACE(legacy.id::text, '-', ''), 8)
        WHERE legacy.scope_type = 'role'
          AND legacy.created_by IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM users AS creator
              WHERE creator.id::text = legacy.created_by
                AND creator.organization_id = legacy.organization_id
                AND creator.deleted_at IS NULL
          )
          AND EXISTS (
              SELECT 1
              FROM agents AS existing
              WHERE existing.id <> legacy.id
                AND existing.organization_id = legacy.organization_id
                AND existing.scope_type = 'user'
                AND existing.scope_id = legacy.created_by
                AND existing.slug = legacy.slug
          )
        """
    )
    op.execute(
        """
        UPDATE agents AS legacy
        SET scope_type = 'user', scope_id = legacy.created_by
        WHERE legacy.scope_type = 'role'
          AND legacy.created_by IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM users AS creator
              WHERE creator.id::text = legacy.created_by
                AND creator.organization_id = legacy.organization_id
                AND creator.deleted_at IS NULL
          )
        """
    )
    op.execute(
        """
        UPDATE agents
        SET scope_type = 'organization', scope_id = NULL, is_active = FALSE
        WHERE scope_type NOT IN ('organization', 'department', 'user')
           OR (scope_type = 'organization' AND scope_id IS NOT NULL)
           OR (scope_type IN ('department', 'user') AND scope_id IS NULL)
        """
    )
    # Execution rows go first. The remaining tables have a historical cycle
    # between skill_folders.active_version_id and skill_versions.
    op.execute("DROP TABLE IF EXISTS skill_executions CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_files CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_folders CASCADE")
    op.execute("DROP TABLE IF EXISTS skill_versions CASCADE")

    op.execute("DROP TABLE IF EXISTS rag_chunks CASCADE")
    op.execute("DROP TABLE IF EXISTS rag_documents CASCADE")
    op.execute("DROP TABLE IF EXISTS rag_folders CASCADE")
    op.execute("DROP TABLE IF EXISTS rag_collections CASCADE")

    op.execute(
        """
        ALTER TABLE agents
          DROP COLUMN IF EXISTS model_alias,
          DROP COLUMN IF EXISTS memory_config,
          DROP COLUMN IF EXISTS workspace_id,
          DROP COLUMN IF EXISTS skill_ids,
          DROP COLUMN IF EXISTS temperature,
          DROP COLUMN IF EXISTS max_tokens,
          DROP COLUMN IF EXISTS rag_collection_ids,
          DROP COLUMN IF EXISTS application_id,
          DROP COLUMN IF EXISTS module_key,
          DROP COLUMN IF EXISTS page_key
        """
    )
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS embedding")

    # Embedding model routing remains supported. Only the platform-owned
    # vector store is removed, so PostgreSQL no longer needs pgvector.
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    raise RuntimeError("0076 已永久退役知识库和用户 Skill；请恢复迁移前数据库快照与匹配镜像")
