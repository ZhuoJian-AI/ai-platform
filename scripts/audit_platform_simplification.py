#!/usr/bin/env python3
"""Read-only deployment gate for the platform simplification contract phase.

The report intentionally separates DSH drain readiness from the longer-lived
Connector retirement gate.  It never alters the database and never prints the
database URL or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import asyncpg


def _database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+asyncpg://"):
        return "postgresql://" + value.removeprefix("postgresql+asyncpg://")
    if value.startswith("postgres+asyncpg://"):
        return "postgresql://" + value.removeprefix("postgres+asyncpg://")
    return value


async def _table_exists(connection: asyncpg.Connection, table: str) -> bool:
    return bool(await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}"))


async def _column_exists(connection: asyncpg.Connection, table: str, column: str) -> bool:
    return bool(
        await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = $1
                  AND column_name = $2
            )
            """,
            table,
            column,
        )
    )


async def _count(connection: asyncpg.Connection, sql: str) -> int:
    return int(await connection.fetchval(sql) or 0)


async def build_report(connection: asyncpg.Connection, *, required_zero_days: int) -> dict[str, Any]:
    database_now = await connection.fetchval("SELECT CURRENT_TIMESTAMP")
    revision = None
    if await _table_exists(connection, "alembic_version"):
        revision = await connection.fetchval("SELECT version_num FROM alembic_version LIMIT 1")

    has_engine = await _column_exists(connection, "agent_runs", "assistant_engine")
    if has_engine:
        dsh_active = await _count(
            connection,
            """
            SELECT COUNT(*)
            FROM agent_runs
            WHERE assistant_engine = 'dsh'
              AND status IN ('queued', 'running')
            """,
        )
    else:
        # Before 0072 every active run may be DSH, so fail closed.
        dsh_active = await _count(
            connection,
            "SELECT COUNT(*) FROM agent_runs WHERE status IN ('queued', 'running')",
        )

    connector_last_call = None
    connector_call_count = 0
    if await _table_exists(connection, "tool_call_logs"):
        connector_last_call = await connection.fetchval(
            """
            SELECT MAX(created_at)
            FROM tool_call_logs
            WHERE connector_id IS NOT NULL OR endpoint_id IS NOT NULL
            """
        )
        connector_call_count = await _count(
            connection,
            """
            SELECT COUNT(*)
            FROM tool_call_logs
            WHERE connector_id IS NOT NULL OR endpoint_id IS NOT NULL
            """,
        )
    quiet_seconds = None
    connector_quiet = connector_last_call is None
    if connector_last_call is not None:
        quiet_seconds = max(0, int((database_now - connector_last_call).total_seconds()))
        connector_quiet = quiet_seconds >= required_zero_days * 24 * 60 * 60

    active_bindings = 0
    if await _table_exists(connection, "enterprise_application_tool_bindings"):
        active_bindings = await _count(
            connection,
            """
            SELECT COUNT(*)
            FROM enterprise_application_tool_bindings
            WHERE deleted_at IS NULL AND is_active IS TRUE
            """,
        )

    invalid_agent_skills = 0
    if await _table_exists(connection, "agents") and await _table_exists(connection, "skill_folders"):
        invalid_agent_skills = await _count(
            connection,
            """
            SELECT COUNT(*)
            FROM agents AS agent
            CROSS JOIN LATERAL jsonb_array_elements_text(
                COALESCE(agent.skill_ids, '[]'::jsonb)
            ) AS skill_id(value)
            LEFT JOIN skill_folders AS folder ON folder.id::text = skill_id.value
            WHERE agent.deleted_at IS NULL
              AND (folder.id IS NULL OR folder.deleted_at IS NOT NULL)
            """,
        )

    team_refs: dict[str, int] = {}
    for table, predicate in (
        ("users", "team_id IS NOT NULL AND deleted_at IS NULL"),
        ("tasks", "team_id IS NOT NULL AND deleted_at IS NULL"),
        ("multimodal_jobs", "team_id IS NOT NULL AND deleted_at IS NULL"),
        ("api_keys", "team_id IS NOT NULL AND is_active IS TRUE AND revoked_at IS NULL"),
        ("llm_providers", "team_id IS NOT NULL AND is_active IS TRUE AND deleted_at IS NULL"),
    ):
        if await _table_exists(connection, table) and await _column_exists(connection, table, "team_id"):
            team_refs[table] = await _count(connection, f"SELECT COUNT(*) FROM {table} WHERE {predicate}")
        else:
            team_refs[table] = 0

    membership_mismatches = 0
    if await _table_exists(connection, "user_department_memberships"):
        membership_mismatches = await _count(
            connection,
            """
            SELECT COUNT(*)
            FROM user_department_memberships AS membership
            JOIN users AS app_user ON app_user.id = membership.user_id
            WHERE app_user.deleted_at IS NULL
              AND membership.department_id IS DISTINCT FROM app_user.department_id
            """,
        )
        membership_mismatches += await _count(
            connection,
            """
            SELECT COUNT(*)
            FROM users AS app_user
            WHERE app_user.deleted_at IS NULL
              AND app_user.department_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM user_department_memberships AS membership
                  WHERE membership.user_id = app_user.id
                    AND membership.department_id = app_user.department_id
              )
            """,
        )

    protected_inventory: dict[str, int] = {}
    for table in (
        "workspaces",
        "workspace_files",
        "workspace_file_versions",
        "rag_collections",
        "memories",
        "tasks",
        "task_messages",
        "task_file_refs",
        "agent_run_events",
        "skill_folders",
        "skill_versions",
    ):
        if await _table_exists(connection, table):
            protected_inventory[table] = await _count(connection, f"SELECT COUNT(*) FROM {table}")

    dsh_gate = dsh_active == 0
    team_gate = sum(team_refs.values()) == 0 and membership_mismatches == 0
    connector_gate = connector_quiet and active_bindings == 0
    skill_gate = invalid_agent_skills == 0
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "databaseNow": database_now.isoformat(),
        "alembicRevision": revision,
        "requiredConnectorZeroDays": required_zero_days,
        "gates": {
            "dshRuntimeRemovalReady": dsh_gate,
            "teamContractReady": team_gate,
            "connectorContractReady": connector_gate,
            "agentSkillReferencesReady": skill_gate,
            "allDestructiveContractsReady": dsh_gate and team_gate and connector_gate and skill_gate,
        },
        "evidence": {
            "assistantEngineColumnPresent": has_engine,
            "activeDshRuns": dsh_active,
            "connectorCallCount": connector_call_count,
            "connectorLastCallAt": connector_last_call.isoformat() if connector_last_call else None,
            "connectorQuietSeconds": quiet_seconds,
            "activeLegacyApplicationBindings": active_bindings,
            "invalidActiveAgentSkillReferences": invalid_agent_skills,
            "activeTeamReferences": team_refs,
            "departmentMembershipMismatches": membership_mismatches,
        },
        "protectedInventory": protected_inventory,
    }


async def _run(args: argparse.Namespace) -> int:
    raw_url = args.database_url or os.getenv("DATABASE_URL", "")
    if not raw_url:
        print("缺少 DATABASE_URL 或 --database-url。", file=sys.stderr)
        return 2
    connection = await asyncpg.connect(_database_url(raw_url), timeout=args.connect_timeout)
    try:
        async with connection.transaction(readonly=True):
            report = await build_report(connection, required_zero_days=args.required_zero_days)
    finally:
        await connection.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["gates"][args.require_gate] else 3


def main() -> int:
    parser = argparse.ArgumentParser(description="只读检查 AI Platform 精简删除门禁")
    parser.add_argument("--database-url", help="PostgreSQL URL；省略时读取 DATABASE_URL")
    parser.add_argument("--required-zero-days", type=int, default=7)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument(
        "--require-gate",
        choices=(
            "dshRuntimeRemovalReady",
            "teamContractReady",
            "connectorContractReady",
            "agentSkillReferencesReady",
            "allDestructiveContractsReady",
        ),
        default="allDestructiveContractsReady",
    )
    args = parser.parse_args()
    if args.required_zero_days < 1:
        parser.error("--required-zero-days 必须大于等于 1")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
