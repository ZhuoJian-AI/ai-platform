"""Remove retired product schema after the native Assistant Core cutover.

Revision ID: 0075_retired_schema_contract
Revises: 0074_user_role_compat
Create Date: 2026-09-09

This is an irreversible contract migration.  A complete PostgreSQL archive and
its restore rehearsal are release prerequisites.  The migration preserves the
append-only AI quota facts, audit rows, AgentRun metadata and every
AgentRunEvent while removing fields that no current runtime consumes.
"""

from alembic import op

revision = "0075_retired_schema_contract"
down_revision = "0074_user_role_compat"
branch_labels = None
depends_on = None


_RETIRED_TABLES = (
    "agent_messages",
    "budget_usage",
    "data_interfaces",
    "data_systems",
    "enterprise_application_tool_bindings",
    "judge_templates",
    "module_deployment_profiles",
    "module_deployments",
    "oauth_authorization_codes",
    "oauth_clients",
    "oauth_refresh_tokens",
    "office_edit_rooms",
    "office_save_events",
    "ontologies",
    "ontology_files",
    "ontology_folders",
    "platform_extension_catalog_entries",
    "platform_extension_release_events",
    "platform_extension_releases",
    "platform_extension_sources",
    "scope_manager_assignments",
    "skills",
    "teams",
    "tool_call_logs",
    "tool_connectors",
    "tool_endpoints",
    "user_department_memberships",
)

_EXPECTED_COLUMNS = (
    "users.role",
    "users.team_id",
    "api_keys.team_id",
    "llm_providers.team_id",
    "tasks.team_id",
    "multimodal_jobs.team_id",
    "audit_logs.team_id",
    "ai_quota_events.team_id",
    "agents.workflow",
    "agents.judge_config",
    "agents.judge_template_id",
    "agents.rag_collection_id",
    "agent_runs.messages",
    "agent_runs.steps",
    "agent_runs.judge_score",
    "agent_runs.assistant_engine",
)

_HANDLED_RETAINED_FOREIGN_KEYS = (
    "agents_judge_template_id_fkey",
    "api_keys_team_id_fkey",
    "fk_multimodal_jobs_team_id_teams",
    "fk_users_team_id",
    "llm_providers_team_id_fkey",
    "tasks_team_id_fkey",
)


def _sql_array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ",".join("'" + value.replace("'", "''") + "'" for value in values) + "]::text[]"


def _assert_contract_preconditions() -> None:
    retired_tables = _sql_array(_RETIRED_TABLES)
    expected_columns = _sql_array(_EXPECTED_COLUMNS)
    handled_foreign_keys = _sql_array(_HANDLED_RETAINED_FOREIGN_KEYS)
    op.execute(
        f"""
        DO $$
        DECLARE
            object_name text;
            table_name_value text;
            column_name_value text;
            unexpected_dependencies text;
        BEGIN
            FOREACH object_name IN ARRAY {retired_tables}
            LOOP
                IF to_regclass('public.' || object_name) IS NULL THEN
                    RAISE EXCEPTION '0075 precondition failed: required retired table % is missing', object_name;
                END IF;
            END LOOP;

            FOREACH object_name IN ARRAY {expected_columns}
            LOOP
                table_name_value := split_part(object_name, '.', 1);
                column_name_value := split_part(object_name, '.', 2);
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = table_name_value
                      AND column_name = column_name_value
                ) THEN
                    RAISE EXCEPTION '0075 precondition failed: required column % is missing', object_name;
                END IF;
            END LOOP;

            IF to_regclass('public.ai_quota_monthly_rollups') IS NULL THEN
                RAISE EXCEPTION '0075 precondition failed: AI quota rollup view is missing';
            END IF;

            SELECT string_agg(
                format('%s: %s -> %s', constraint_row.conname, source_rel.relname, target_rel.relname),
                ', ' ORDER BY source_rel.relname, constraint_row.conname
            )
            INTO unexpected_dependencies
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS source_rel ON source_rel.oid = constraint_row.conrelid
            JOIN pg_namespace AS source_namespace ON source_namespace.oid = source_rel.relnamespace
            JOIN pg_class AS target_rel ON target_rel.oid = constraint_row.confrelid
            JOIN pg_namespace AS target_namespace ON target_namespace.oid = target_rel.relnamespace
            WHERE constraint_row.contype = 'f'
              AND source_namespace.nspname = 'public'
              AND target_namespace.nspname = 'public'
              AND target_rel.relname = ANY({retired_tables})
              AND source_rel.relname <> ALL({retired_tables})
              AND constraint_row.conname <> ALL({handled_foreign_keys});
            IF unexpected_dependencies IS NOT NULL THEN
                RAISE EXCEPTION
                    '0075 precondition failed: unexpected retained foreign keys: %',
                    unexpected_dependencies;
            END IF;

            SELECT string_agg(
                format('%s.%s -> %s', dependent_namespace.nspname, dependent_view.relname, source_rel.relname),
                ', ' ORDER BY dependent_namespace.nspname, dependent_view.relname, source_rel.relname
            )
            INTO unexpected_dependencies
            FROM pg_depend AS dependency
            JOIN pg_rewrite AS rewrite_rule ON rewrite_rule.oid = dependency.objid
            JOIN pg_class AS dependent_view ON dependent_view.oid = rewrite_rule.ev_class
            JOIN pg_namespace AS dependent_namespace ON dependent_namespace.oid = dependent_view.relnamespace
            JOIN pg_class AS source_rel ON source_rel.oid = dependency.refobjid
            JOIN pg_namespace AS source_namespace ON source_namespace.oid = source_rel.relnamespace
            WHERE dependency.classid = 'pg_rewrite'::regclass
              AND dependent_view.relkind IN ('v', 'm')
              AND source_namespace.nspname = 'public'
              AND source_rel.relname = ANY({retired_tables});
            IF unexpected_dependencies IS NOT NULL THEN
                RAISE EXCEPTION
                    '0075 precondition failed: views still depend on retired tables: %',
                    unexpected_dependencies;
            END IF;

            IF EXISTS (
                SELECT 1 FROM agent_runs
                WHERE assistant_engine = 'dsh' AND status IN ('queued', 'running')
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: DSH runs are still active';
            END IF;

            IF EXISTS (
                SELECT 1 FROM api_keys
                WHERE (scope_type = 'team' OR team_id IS NOT NULL)
                  AND is_active IS TRUE
                  AND revoked_at IS NULL
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: active Team API keys still exist';
            END IF;
            IF EXISTS (
                SELECT 1 FROM llm_providers
                WHERE (scope_type = 'team' OR team_id IS NOT NULL) AND is_active IS TRUE
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: active Team model providers still exist';
            END IF;
            IF EXISTS (
                SELECT 1 FROM workspaces
                WHERE scope_type = 'team' AND (is_active IS TRUE OR deleted_at IS NULL)
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: active Team workspaces still exist';
            END IF;
            IF EXISTS (SELECT 1 FROM dlp_rules WHERE scope_type = 'team' AND is_active IS TRUE) THEN
                RAISE EXCEPTION '0075 precondition failed: active Team DLP rules still exist';
            END IF;
            IF EXISTS (SELECT 1 FROM users WHERE team_id IS NOT NULL) THEN
                RAISE EXCEPTION '0075 precondition failed: users still reference Team membership';
            END IF;

            IF EXISTS (
                SELECT 1 FROM agents WHERE scope_type = 'team'
                UNION ALL SELECT 1 FROM memories WHERE scope_type = 'team'
                UNION ALL SELECT 1 FROM rag_collections WHERE scope_type = 'team'
                UNION ALL SELECT 1 FROM skill_folders WHERE scope_type = 'team'
                UNION ALL SELECT 1 FROM enterprise_application_grants WHERE scope_type = 'team'
                UNION ALL SELECT 1 FROM enterprise_application_event_routes WHERE target_scope_type = 'team'
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: retained authorization resources still use Team scope';
            END IF;

            IF EXISTS (
                SELECT 1 FROM api_keys AS resource
                WHERE (resource.scope_type = 'team' OR resource.team_id IS NOT NULL)
                  AND NOT EXISTS (SELECT 1 FROM teams WHERE teams.id = resource.team_id)
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: Team API key has no Team-to-department mapping';
            END IF;
            IF EXISTS (
                SELECT 1 FROM llm_providers AS resource
                WHERE (resource.scope_type = 'team' OR resource.team_id IS NOT NULL)
                  AND NOT EXISTS (SELECT 1 FROM teams WHERE teams.id = resource.team_id)
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: Team provider has no Team-to-department mapping';
            END IF;
            IF EXISTS (
                SELECT 1 FROM dlp_rules AS resource
                WHERE resource.scope_type = 'team'
                  AND NOT EXISTS (SELECT 1 FROM teams WHERE teams.id = resource.scope_id)
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: Team DLP rule has no Team-to-department mapping';
            END IF;

            IF EXISTS (
                SELECT 1 FROM audit_logs
                WHERE team_id IS NOT NULL
                  AND jsonb_typeof(metadata) IS DISTINCT FROM 'object'
            ) THEN
                RAISE EXCEPTION
                    '0075 precondition failed: audit Team metadata is not a JSON object';
            END IF;
            IF EXISTS (
                SELECT 1 FROM audit_logs
                WHERE team_id IS NOT NULL
                  AND metadata ? 'legacy_team_id'
                  AND metadata ->> 'legacy_team_id' IS DISTINCT FROM team_id
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: audit legacy Team metadata conflicts with team_id';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM ai_quota_events AS event_row
                WHERE event_row.team_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM ai_quota_events AS team_scope
                      WHERE team_scope.reservation_id = event_row.reservation_id
                        AND team_scope.organization_id = event_row.organization_id
                        AND team_scope.event_type = event_row.event_type
                        AND team_scope.scope_type = 'team'
                        AND team_scope.scope_id = event_row.team_id
                  )
            ) THEN
                RAISE EXCEPTION
                    '0075 precondition failed: quota Team context lacks an equivalent Team scope fact';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM ai_quota_events
                GROUP BY
                    reservation_id,
                    CASE WHEN scope_type = 'team' THEN 'legacy_team' ELSE scope_type END,
                    scope_id,
                    event_type
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION '0075 precondition failed: quota legacy Team normalization would collide';
            END IF;

            IF EXISTS (
                SELECT 1 FROM agents
                WHERE workflow <> '[]'::jsonb
                   OR judge_config <> '{{}}'::jsonb
                   OR judge_template_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    '0075 precondition failed: Agent workflow or Judge configuration still contains active data';
            END IF;
        END $$;
        """
    )


def _migrate_retained_history() -> None:
    # Keep a legacy single-RAG binding in the authoritative multi-RAG list.
    op.execute(
        """
        UPDATE agents
        SET rag_collection_ids = CASE
            WHEN COALESCE(rag_collection_ids, '[]'::jsonb) @> jsonb_build_array(rag_collection_id::text)
                THEN COALESCE(rag_collection_ids, '[]'::jsonb)
            ELSE COALESCE(rag_collection_ids, '[]'::jsonb) || jsonb_build_array(rag_collection_id::text)
        END,
        updated_at = CURRENT_TIMESTAMP
        WHERE rag_collection_id IS NOT NULL
        """
    )

    # Disabled credentials keep their former department without becoming active.
    op.execute(
        """
        UPDATE api_keys AS resource
        SET department_id = team_row.department_id,
            scope_type = 'department',
            team_id = NULL,
            updated_at = CURRENT_TIMESTAMP
        FROM teams AS team_row
        WHERE resource.team_id = team_row.id
          AND (resource.scope_type = 'team' OR resource.team_id IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE llm_providers AS resource
        SET department_id = team_row.department_id,
            scope_type = 'department',
            team_id = NULL,
            updated_at = CURRENT_TIMESTAMP
        FROM teams AS team_row
        WHERE resource.team_id = team_row.id
          AND (resource.scope_type = 'team' OR resource.team_id IS NOT NULL)
        """
    )
    op.execute(
        """
        UPDATE dlp_rules AS resource
        SET scope_type = 'department',
            scope_id = team_row.department_id,
            updated_at = CURRENT_TIMESTAMP
        FROM teams AS team_row
        WHERE resource.scope_type = 'team' AND resource.scope_id = team_row.id
        """
    )
    # Empty, retired Team workspaces remain visibly historical and cannot be
    # mistaken for an active department workspace after the Team table is gone.
    op.execute(
        """
        UPDATE workspaces
        SET scope_type = 'legacy_team', updated_at = CURRENT_TIMESTAMP
        WHERE scope_type = 'team'
        """
    )
    op.execute("UPDATE tasks SET team_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE team_id IS NOT NULL")
    op.execute(
        "UPDATE multimodal_jobs SET team_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE team_id IS NOT NULL"
    )

    # Audit rows remain one-for-one.  The historical dimension moves into the
    # existing metadata document before the obsolete column is removed.
    op.execute(
        """
        UPDATE audit_logs
        SET metadata = COALESCE(metadata, '{}'::jsonb)
            || jsonb_build_object('legacy_team_id', team_id)
        WHERE team_id IS NOT NULL
        """
    )

    # The database trigger is restored in the same transaction.  Team scope
    # facts become a non-authorizing historical scope; redundant team_id values
    # on the organization/department/API-key facts can then be removed.
    op.execute("DROP MATERIALIZED VIEW ai_quota_monthly_rollups")
    op.execute("DROP TRIGGER trg_ai_quota_events_append_only ON ai_quota_events")
    op.execute("UPDATE ai_quota_events SET scope_type = 'legacy_team' WHERE scope_type = 'team'")
    op.execute("UPDATE ai_quota_events SET team_id = NULL WHERE team_id IS NOT NULL")
    op.execute(
        """
        CREATE TRIGGER trg_ai_quota_events_append_only
        BEFORE UPDATE OR DELETE ON ai_quota_events
        FOR EACH ROW EXECUTE FUNCTION reject_ai_quota_event_mutation()
        """
    )


def _drop_retired_columns() -> None:
    op.drop_index("ix_agent_runs_engine_status", table_name="agent_runs")
    op.drop_constraint("ck_agent_runs_assistant_engine", "agent_runs", type_="check")
    for column in ("assistant_engine", "messages", "steps", "judge_score"):
        op.drop_column("agent_runs", column)

    op.drop_index("ix_agents_judge_template_id", table_name="agents")
    op.drop_constraint("agents_judge_template_id_fkey", "agents", type_="foreignkey")
    op.drop_index("ix_agents_rag_collection_id", table_name="agents")
    op.drop_constraint("agents_rag_collection_id_fkey", "agents", type_="foreignkey")
    for column in ("workflow", "judge_config", "judge_template_id", "rag_collection_id"):
        op.drop_column("agents", column)

    op.drop_constraint("fk_users_team_id", "users", type_="foreignkey")
    op.drop_index("ix_users_team_id", table_name="users")
    op.drop_column("users", "team_id")
    op.drop_column("users", "role")

    op.drop_constraint("tasks_team_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "team_id")
    op.drop_constraint("fk_multimodal_jobs_team_id_teams", "multimodal_jobs", type_="foreignkey")
    op.drop_index("ix_multimodal_jobs_team_id", table_name="multimodal_jobs")
    op.drop_column("multimodal_jobs", "team_id")

    op.drop_constraint("api_keys_team_id_fkey", "api_keys", type_="foreignkey")
    op.drop_index("ix_api_keys_team_id", table_name="api_keys")
    op.drop_column("api_keys", "team_id")
    op.drop_constraint("llm_providers_team_id_fkey", "llm_providers", type_="foreignkey")
    op.drop_index("ix_llm_providers_team_id", table_name="llm_providers")
    op.drop_column("llm_providers", "team_id")

    op.drop_column("audit_logs", "team_id")
    op.drop_column("ai_quota_events", "team_id")


def _drop_retired_tables() -> None:
    # Children precede their parents.  Every relationship is named and audited
    # by the precondition query, so a newly introduced dependency fails closed.
    for table in (
        "enterprise_application_tool_bindings",
        "tool_call_logs",
        "tool_endpoints",
        "tool_connectors",
        "data_interfaces",
        "data_systems",
        "agent_messages",
        "office_save_events",
        "office_edit_rooms",
        "oauth_refresh_tokens",
        "oauth_authorization_codes",
        "oauth_clients",
        "ontology_files",
        "ontology_folders",
        "ontologies",
        "module_deployments",
        "module_deployment_profiles",
        "platform_extension_catalog_entries",
        "platform_extension_release_events",
        "platform_extension_releases",
        "platform_extension_sources",
        "user_department_memberships",
        "scope_manager_assignments",
        "skills",
        "judge_templates",
        "budget_usage",
        "teams",
    ):
        op.drop_table(table)


def _recreate_quota_rollup() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW ai_quota_monthly_rollups AS
        SELECT
            date_trunc('month', created_at AT TIME ZONE 'UTC')::date AS period_month,
            organization_id,
            scope_type,
            scope_id,
            COALESCE(department_id, '') AS department_key,
            COALESCE(api_key_id, '') AS api_key_key,
            COALESCE(provider_id, '') AS provider_key,
            COALESCE(operation, '') AS operation_key,
            COUNT(*) FILTER (WHERE event_type = 'reserved')::bigint AS admitted_operations,
            COALESCE(SUM(reserved_tokens) FILTER (WHERE event_type = 'reserved'), 0)::bigint
                AS reserved_tokens,
            COALESCE(SUM(reserved_credits) FILTER (WHERE event_type = 'reserved'), 0)::bigint
                AS admitted_credits,
            COALESCE(SUM(actual_tokens) FILTER (WHERE event_type = 'settled'), 0)::bigint
                AS actual_tokens,
            COUNT(*) FILTER (
                WHERE event_type = 'settled' AND outcome LIKE 'failed%'
            )::bigint AS failed_operations,
            MAX(created_at) AS refreshed_through
        FROM ai_quota_events
        GROUP BY
            date_trunc('month', created_at AT TIME ZONE 'UTC')::date,
            organization_id,
            scope_type,
            scope_id,
            COALESCE(department_id, ''),
            COALESCE(api_key_id, ''),
            COALESCE(provider_id, ''),
            COALESCE(operation, '')
        WITH NO DATA
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_ai_quota_monthly_rollups_dimensions
        ON ai_quota_monthly_rollups (
            period_month,
            organization_id,
            scope_type,
            scope_id,
            department_key,
            api_key_key,
            provider_key,
            operation_key
        )
        """
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    _assert_contract_preconditions()
    _migrate_retained_history()
    _drop_retired_columns()
    _drop_retired_tables()
    _recreate_quota_rollup()


def downgrade() -> None:
    raise RuntimeError(
        "0075_retired_schema_contract 不可逆；请停止写入并恢复迁移前 PostgreSQL 归档和匹配镜像"
    )
