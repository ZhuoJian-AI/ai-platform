"""Add durable AI quota ledger and modality-neutral credit budgets.

Revision ID: 0066_ai_quota_ledger
Revises: 0065_mcp_oauth
Create Date: 2026-09-04

Legacy USD cap columns remain readable for schema compatibility, but migration
clears historical values before freezing them.  A versioned provider price
catalogue does not exist yet, so retaining or accepting dollar caps would
falsely imply that the platform can enforce them.
"""

import sqlalchemy as sa

from alembic import op

revision = "0066_ai_quota_ledger"
down_revision = "0065_mcp_oauth"
branch_labels = None
depends_on = None


_SCOPED_TABLES = ("organizations", "departments", "teams", "api_keys")


def upgrade() -> None:
    for table in _SCOPED_TABLES:
        op.add_column(table, sa.Column("budget_cap_credits", sa.BigInteger(), nullable=True))
        op.create_check_constraint(
            f"ck_{table}_budget_cap_credits_nonnegative",
            table,
            "budget_cap_credits IS NULL OR budget_cap_credits >= 0",
        )

    op.create_table(
        "ai_quota_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reservation_id", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("team_id", sa.String(length=36), nullable=True),
        sa.Column("api_key_id", sa.String(length=36), nullable=True),
        sa.Column("provider_id", sa.String(length=36), nullable=True),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=True),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_credits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("actual_tokens", sa.BigInteger(), nullable=True),
        sa.Column("actual_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("actual_output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("reserved_tokens >= 0", name="ck_ai_quota_events_reserved_tokens"),
        sa.CheckConstraint("reserved_credits >= 0", name="ck_ai_quota_events_reserved_credits"),
        sa.CheckConstraint(
            "event_type IN ('reserved', 'settled')",
            name="ck_ai_quota_events_event_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reservation_id",
            "scope_type",
            "scope_id",
            "event_type",
            name="uq_ai_quota_event_phase",
        ),
    )
    op.create_index(
        "ix_ai_quota_events_reservation_id",
        "ai_quota_events",
        ["reservation_id"],
    )
    op.create_index(
        "ix_ai_quota_events_org_created",
        "ai_quota_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_ai_quota_events_scope_created",
        "ai_quota_events",
        ["scope_type", "scope_id", "created_at"],
    )

    # Append-only enforcement is in the database, not merely a service
    # convention, so revoked keys and failed calls cannot disappear from usage.
    op.execute(
        """
        CREATE FUNCTION reject_ai_quota_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ai_quota_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ai_quota_events_append_only
        BEFORE UPDATE OR DELETE ON ai_quota_events
        FOR EACH ROW EXECUTE FUNCTION reject_ai_quota_event_mutation()
        """
    )

    # Historical USD values were never backed by an immutable price catalogue.
    # Clear them before installing the guard so an upgrade cannot leave tenants
    # apparently capped by a value the admission path cannot enforce reliably.
    for table in _SCOPED_TABLES:
        op.execute(f"UPDATE {table} SET budget_cap_usd = NULL WHERE budget_cap_usd IS NOT NULL")

    # Keep the legacy columns for compatibility, but reject every new/non-null
    # USD cap until a trustworthy, versioned price ledger is shipped.
    op.execute(
        """
        CREATE FUNCTION reject_new_usd_budget_cap() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.budget_cap_usd IS NOT NULL THEN
                    RAISE EXCEPTION 'USD budgets are legacy read-only; use token or credit budgets';
                END IF;
            ELSIF NEW.budget_cap_usd IS NOT NULL AND
                  NEW.budget_cap_usd IS DISTINCT FROM OLD.budget_cap_usd THEN
                RAISE EXCEPTION 'USD budgets are legacy read-only; use token or credit budgets';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in _SCOPED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_freeze_usd_budget
            BEFORE INSERT OR UPDATE OF budget_cap_usd ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_new_usd_budget_cap();
            """
        )


def downgrade() -> None:
    for table in _SCOPED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_freeze_usd_budget ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_new_usd_budget_cap()")
    op.execute("DROP TRIGGER IF EXISTS trg_ai_quota_events_append_only ON ai_quota_events")
    op.execute("DROP FUNCTION IF EXISTS reject_ai_quota_event_mutation()")
    op.drop_index("ix_ai_quota_events_scope_created", table_name="ai_quota_events")
    op.drop_index("ix_ai_quota_events_org_created", table_name="ai_quota_events")
    op.drop_index("ix_ai_quota_events_reservation_id", table_name="ai_quota_events")
    op.drop_table("ai_quota_events")
    for table in reversed(_SCOPED_TABLES):
        op.drop_constraint(
            f"ck_{table}_budget_cap_credits_nonnegative",
            table,
            type_="check",
        )
        op.drop_column(table, "budget_cap_credits")
