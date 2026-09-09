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

    # Embedding is no longer a platform model capability.  Preserve the full
    # pre-migration database snapshot, then remove embedding-only deployments
    # and their legacy model selectors without disturbing chat/multimodal
    # deployments that share the same provider.
    op.execute(
        """
        CREATE TEMP TABLE retired_embedding_models ON COMMIT DROP AS
        SELECT DISTINCT provider.organization_id, deployment.provider_id, deployment.model_id
        FROM model_deployments AS deployment
        JOIN llm_providers AS provider ON provider.id = deployment.provider_id
        WHERE deployment.adapter = 'openai_embeddings'
           OR deployment.capabilities ? 'embedding'
        """
    )
    op.execute(
        """
        UPDATE model_deployments
        SET capabilities = capabilities - 'embedding'
        WHERE adapter <> 'openai_embeddings'
          AND capabilities ? 'embedding'
          AND jsonb_array_length(capabilities) > 1
        """
    )
    op.execute(
        """
        DELETE FROM model_deployments
        WHERE adapter = 'openai_embeddings'
           OR capabilities ? 'embedding'
        """
    )
    op.execute(
        """
        UPDATE llm_providers AS provider
        SET supported_models = COALESCE(
            (
                SELECT jsonb_agg(item.value ORDER BY item.ordinality)
                FROM jsonb_array_elements_text(COALESCE(provider.supported_models, '[]'::jsonb))
                     WITH ORDINALITY AS item(value, ordinality)
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM retired_embedding_models AS retired
                    WHERE retired.provider_id = provider.id
                      AND retired.model_id = item.value
                      AND NOT EXISTS (
                          SELECT 1
                          FROM model_deployments AS surviving
                          WHERE surviving.provider_id = provider.id
                            AND surviving.model_id = retired.model_id
                            AND surviving.deleted_at IS NULL
                      )
                )
            ),
            '[]'::jsonb
        )
        WHERE EXISTS (
            SELECT 1 FROM retired_embedding_models AS retired
            WHERE retired.provider_id = provider.id
        )
        """
    )
    op.execute(
        """
        UPDATE api_keys AS api_key
        SET allowed_models = COALESCE(
            (
                SELECT jsonb_agg(item.value ORDER BY item.ordinality)
                FROM jsonb_array_elements_text(COALESCE(api_key.allowed_models, '[]'::jsonb))
                     WITH ORDINALITY AS item(value, ordinality)
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM retired_embedding_models AS retired
                    WHERE retired.organization_id = api_key.organization_id
                      AND retired.model_id = item.value
                      AND NOT EXISTS (
                          SELECT 1
                          FROM model_deployments AS surviving
                          JOIN llm_providers AS surviving_provider
                            ON surviving_provider.id = surviving.provider_id
                          WHERE surviving_provider.organization_id = api_key.organization_id
                            AND surviving.model_id = retired.model_id
                            AND surviving.deleted_at IS NULL
                      )
                )
            ),
            '[]'::jsonb
        )
        WHERE EXISTS (
            SELECT 1 FROM retired_embedding_models AS retired
            WHERE retired.organization_id = api_key.organization_id
              AND retired.model_id IN (
                  SELECT value
                  FROM jsonb_array_elements_text(COALESCE(api_key.allowed_models, '[]'::jsonb))
              )
        )
        """
    )
    op.execute("ALTER TABLE model_deployments DROP COLUMN IF EXISTS embedding_dimensions")

    # With RAG, memory vectors and embedding routing retired, PostgreSQL no
    # longer needs pgvector.
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    raise RuntimeError("0076 已永久退役知识库和用户 Skill；请恢复迁移前数据库快照与匹配镜像")
