"""Add monthly AI quota rollups and a large-ledger time index.

Revision ID: 0068_ai_quota_rollups
Revises: 0067_audio_team_scope
Create Date: 2026-09-04

The fact ledger remains append-only. Closed-period deletion is intentionally
not automated until an audit-retention and archive-restore policy is approved.
"""

from alembic import op

revision = "0068_ai_quota_rollups"
down_revision = "0067_audio_team_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_ai_quota_events_created_at_brin "
        "ON ai_quota_events USING BRIN (created_at)"
    )
    op.execute(
        """
        CREATE MATERIALIZED VIEW ai_quota_monthly_rollups AS
        SELECT
            date_trunc('month', created_at AT TIME ZONE 'UTC')::date AS period_month,
            organization_id,
            scope_type,
            scope_id,
            COALESCE(department_id, '') AS department_key,
            COALESCE(team_id, '') AS team_key,
            COALESCE(api_key_id, '') AS api_key_key,
            COALESCE(provider_id, '') AS provider_key,
            COALESCE(operation, '') AS operation_key,
            COUNT(*) FILTER (WHERE event_type = 'reserved')::bigint AS admitted_operations,
            COALESCE(
                SUM(reserved_tokens) FILTER (WHERE event_type = 'reserved'),
                0
            )::bigint AS reserved_tokens,
            COALESCE(
                SUM(reserved_credits) FILTER (WHERE event_type = 'reserved'),
                0
            )::bigint AS admitted_credits,
            COALESCE(
                SUM(actual_tokens) FILTER (WHERE event_type = 'settled'),
                0
            )::bigint AS actual_tokens,
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
            COALESCE(team_id, ''),
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
            team_key,
            api_key_key,
            provider_key,
            operation_key
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS ai_quota_monthly_rollups")
    op.execute("DROP INDEX IF EXISTS ix_ai_quota_events_created_at_brin")
