"""separate provider vendor credentials from model deployments

Revision ID: 0037_model_gateway
Revises: 0036_skill_timestamp_defaults
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0037_model_gateway"
down_revision = "0036_skill_timestamp_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_providers", sa.Column("vendor", sa.String(50), nullable=False, server_default="custom"))
    op.add_column("llm_providers", sa.Column("region", sa.String(64), nullable=True))
    op.add_column("llm_providers", sa.Column("workspace_id", sa.String(255), nullable=True))
    op.create_index("ix_llm_providers_vendor", "llm_providers", ["vendor"])
    op.execute("""
        UPDATE llm_providers
        SET vendor = CASE
            WHEN provider_type = 'openai' THEN 'openai'
            WHEN provider_type = 'anthropic' THEN 'anthropic'
            WHEN provider_type = 'azure_openai' THEN 'azure_openai'
            ELSE 'custom'
        END
    """)

    op.create_table(
        "model_deployments",
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("adapter", sa.String(64), nullable=False, server_default="openai_chat_completions"),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("base_url_override", sa.Text(), nullable=True),
        sa.Column("endpoint_path", sa.String(255), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("routing_priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="unverified"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_deployments_provider_id", "model_deployments", ["provider_id"])
    op.create_index("ix_model_deployments_model_id", "model_deployments", ["model_id"])
    op.create_index("ix_model_deployments_verification_status", "model_deployments", ["verification_status"])
    op.create_index(
        "uq_model_deployment_provider_model_adapter_active",
        "model_deployments",
        ["provider_id", "model_id", "adapter"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Existing providers remain routable. New deployments require an explicit capability test.
    op.execute("""
        INSERT INTO model_deployments (
            id, provider_id, model_id, adapter, capabilities, endpoint_path,
            routing_priority, is_active, verification_status, config, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), p.id, model_id,
            CASE
                WHEN COALESCE(p.config->'image_generation'->>'enabled', 'false')::boolean
                     AND p.config->'image_generation'->>'model' = model_id THEN 'openai_images'
                WHEN p.provider_type = 'anthropic' THEN 'anthropic_messages'
                ELSE 'openai_chat_completions'
            END,
            CASE
                WHEN COALESCE(p.config->'image_generation'->>'enabled', 'false')::boolean
                     AND p.config->'image_generation'->>'model' = model_id
                    THEN '["image_generation"]'::jsonb
                WHEN COALESCE(p.config->'model_capabilities'->model_id->>'vision', 'false')::boolean
                    THEN '["chat", "vision"]'::jsonb
                ELSE '["chat"]'::jsonb
            END,
            CASE
                WHEN p.config->'image_generation'->>'model' = model_id
                    THEN COALESCE(p.config->'image_generation'->>'endpoint_path', '/images/generations')
                ELSE NULL
            END,
            p.priority, p.is_active, 'legacy', '{}'::jsonb, p.created_at, p.updated_at
        FROM llm_providers p
        CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(p.supported_models, '[]'::jsonb)) AS model(model_id)
        WHERE p.deleted_at IS NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("model_deployments")
    op.drop_index("ix_llm_providers_vendor", table_name="llm_providers")
    op.drop_column("llm_providers", "workspace_id")
    op.drop_column("llm_providers", "region")
    op.drop_column("llm_providers", "vendor")
