#!/usr/bin/env python3
"""Build a fail-closed, read-only preflight report for retired database objects.

This script does not delete, update, lock, or archive data.  It reports exact
row counts, retained-table foreign keys, active compatibility references, and
manual evidence still required before a future contract migration is written.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import asyncpg

RETIRED_TABLES = (
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
    "rag_chunks",
    "rag_collections",
    "rag_documents",
    "rag_folders",
    "scope_manager_assignments",
    "skill_executions",
    "skill_files",
    "skill_folders",
    "skill_versions",
    "skills",
    "teams",
    "tool_connectors",
    "tool_endpoints",
    "user_department_memberships",
)

# Tool-call history remains a separately audited retirement target.
CONDITIONAL_RETIRED_TABLES = ("tool_call_logs",)


def _database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("postgresql+asyncpg://"):
        return "postgresql://" + value.removeprefix("postgresql+asyncpg://")
    if value.startswith("postgres+asyncpg://"):
        return "postgresql://" + value.removeprefix("postgres+asyncpg://")
    return value


def _is_local_host(host: str | None) -> bool:
    normalized = (host or "").strip("[]").lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_private
    except ValueError:
        return False


def _assert_connection_scope(database_url: str, *, allow_remote: bool) -> None:
    host = urlsplit(_database_url(database_url)).hostname
    if not _is_local_host(host) and not allow_remote:
        raise ValueError("远端数据库只读检查必须显式传入 --allow-remote-read-only")


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def _table_exists(connection: asyncpg.Connection, schema: str, table: str) -> bool:
    return bool(await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.{table}"))


async def _column_exists(
    connection: asyncpg.Connection,
    schema: str,
    table: str,
    column: str,
) -> bool:
    return bool(
        await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2 AND column_name = $3
            )
            """,
            schema,
            table,
            column,
        )
    )


async def _count(connection: asyncpg.Connection, sql: str, *args: object) -> int:
    return int(await connection.fetchval(sql, *args) or 0)


async def _retired_table_inventory(
    connection: asyncpg.Connection,
    schema: str,
    table: str,
) -> dict[str, Any]:
    if not await _table_exists(connection, schema, table):
        return {"present": False, "rowCount": 0, "columns": []}
    columns = await connection.fetch(
        """
        SELECT column_name, udt_name, is_nullable
        FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
        ORDER BY ordinal_position
        """,
        schema,
        table,
    )
    row_count = await _count(
        connection,
        f"SELECT COUNT(*) FROM {_quote_ident(schema)}.{_quote_ident(table)}",
    )
    return {
        "present": True,
        "rowCount": row_count,
        "columns": [
            {
                "name": str(row["column_name"]),
                "type": str(row["udt_name"]),
                "nullable": row["is_nullable"] == "YES",
            }
            for row in columns
        ],
    }


async def _foreign_key_dependencies(
    connection: asyncpg.Connection,
    schema: str,
    retired_tables: set[str],
) -> list[dict[str, Any]]:
    rows = await connection.fetch(
        """
        SELECT constraint_row.conname,
               source_rel.relname AS source_table,
               target_rel.relname AS target_table,
               pg_get_constraintdef(constraint_row.oid, true) AS definition
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS source_rel ON source_rel.oid = constraint_row.conrelid
        JOIN pg_namespace AS source_namespace ON source_namespace.oid = source_rel.relnamespace
        JOIN pg_class AS target_rel ON target_rel.oid = constraint_row.confrelid
        JOIN pg_namespace AS target_namespace ON target_namespace.oid = target_rel.relnamespace
        WHERE constraint_row.contype = 'f'
          AND source_namespace.nspname = $1
          AND target_namespace.nspname = $1
        ORDER BY source_rel.relname, constraint_row.conname
        """,
        schema,
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        source = str(row["source_table"])
        target = str(row["target_table"])
        if source not in retired_tables and target not in retired_tables:
            continue
        result.append(
            {
                "constraint": str(row["conname"]),
                "sourceTable": source,
                "targetTable": target,
                "definition": str(row["definition"]),
                "retainedSourceBlocksDrop": source not in retired_tables and target in retired_tables,
            }
        )
    return result


async def _view_dependencies(
    connection: asyncpg.Connection,
    schema: str,
    retired_tables: set[str],
) -> list[dict[str, str]]:
    rows = await connection.fetch(
        """
        SELECT DISTINCT dependent_namespace.nspname AS view_schema,
                        dependent_view.relname AS view_name,
                        source_rel.relname AS source_table,
                        dependent_view.relkind
        FROM pg_depend AS dependency
        JOIN pg_rewrite AS rewrite_rule ON rewrite_rule.oid = dependency.objid
        JOIN pg_class AS dependent_view ON dependent_view.oid = rewrite_rule.ev_class
        JOIN pg_namespace AS dependent_namespace
          ON dependent_namespace.oid = dependent_view.relnamespace
        JOIN pg_class AS source_rel ON source_rel.oid = dependency.refobjid
        JOIN pg_namespace AS source_namespace ON source_namespace.oid = source_rel.relnamespace
        WHERE dependency.classid = 'pg_rewrite'::regclass
          AND dependent_view.relkind IN ('v', 'm')
          AND source_namespace.nspname = $1
          AND source_rel.relname = ANY($2::text[])
        ORDER BY dependent_namespace.nspname, dependent_view.relname, source_rel.relname
        """,
        schema,
        sorted(retired_tables),
    )
    return [
        {
            "viewSchema": str(row["view_schema"]),
            "viewName": str(row["view_name"]),
            "sourceTable": str(row["source_table"]),
            "viewKind": "materialized" if row["relkind"] == "m" else "view",
        }
        for row in rows
    ]


async def _all_non_null_column_references(
    connection: asyncpg.Connection,
    schema: str,
    column: str,
) -> dict[str, int]:
    rows = await connection.fetch(
        """
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = $1 AND column_name = $2
        ORDER BY table_name
        """,
        schema,
        column,
    )
    references: dict[str, int] = {}
    for row in rows:
        table = str(row["table_name"])
        references[table] = await _count(
            connection,
            f"SELECT COUNT(*) FROM {_quote_ident(schema)}.{_quote_ident(table)} "
            f"WHERE {_quote_ident(column)} IS NOT NULL",
        )
    return references


async def _team_scope_references(
    connection: asyncpg.Connection,
    schema: str,
) -> dict[str, int]:
    rows = await connection.fetch(
        """
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = $1 AND column_name = 'scope_type'
        ORDER BY table_name
        """,
        schema,
    )
    references: dict[str, int] = {}
    for row in rows:
        table = str(row["table_name"])
        references[table] = await _count(
            connection,
            f"SELECT COUNT(*) FROM {_quote_ident(schema)}.{_quote_ident(table)} "
            "WHERE scope_type = 'team'",
        )
    return references


async def _legacy_payload_count(
    connection: asyncpg.Connection,
    schema: str,
    table: str,
    column: str,
) -> int:
    if not await _column_exists(connection, schema, table, column):
        return 0
    qualified = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    quoted_column = _quote_ident(column)
    return await _count(
        connection,
        f"SELECT COUNT(*) FROM {qualified} "
        f"WHERE {quoted_column} IS NOT NULL "
        f"AND {quoted_column}::text NOT IN ('', '{{}}', '[]', 'null')",
    )


async def build_report(connection: asyncpg.Connection, *, schema: str) -> dict[str, Any]:
    retired_set = set(RETIRED_TABLES) | set(CONDITIONAL_RETIRED_TABLES)
    inventory = {
        table: await _retired_table_inventory(connection, schema, table)
        for table in (*RETIRED_TABLES, *CONDITIONAL_RETIRED_TABLES)
    }
    foreign_keys = await _foreign_key_dependencies(connection, schema, retired_set)
    view_dependencies = await _view_dependencies(connection, schema, retired_set)
    hard_blockers: list[dict[str, Any]] = []

    retained_fk_blockers = [item for item in foreign_keys if item["retainedSourceBlocksDrop"]]
    if retained_fk_blockers:
        hard_blockers.append(
            {
                "code": "retained_foreign_keys",
                "messageZh": "仍有保留表通过外键依赖待退役表，必须先迁移或删除这些外键。",
                "count": len(retained_fk_blockers),
            }
        )

    if view_dependencies:
        hard_blockers.append(
            {
                "code": "dependent_views",
                "messageZh": "仍有视图或物化视图依赖待退役表，必须显式处理，禁止使用 CASCADE 绕过。",
                "count": len(view_dependencies),
            }
        )

    active_dsh_runs = 0
    if await _table_exists(connection, schema, "agent_runs"):
        if await _column_exists(connection, schema, "agent_runs", "assistant_engine"):
            active_dsh_runs = await _count(
                connection,
                f"SELECT COUNT(*) FROM {_quote_ident(schema)}.agent_runs "
                "WHERE assistant_engine = 'dsh' AND status IN ('queued', 'running')",
            )
        else:
            active_dsh_runs = await _count(
                connection,
                f"SELECT COUNT(*) FROM {_quote_ident(schema)}.agent_runs "
                "WHERE status IN ('queued', 'running')",
            )
    if active_dsh_runs:
        hard_blockers.append(
            {
                "code": "active_dsh_runs",
                "messageZh": "仍有 DSH 任务排队或执行中。",
                "count": active_dsh_runs,
            }
        )

    team_id_references = await _all_non_null_column_references(connection, schema, "team_id")
    team_scope_references = await _team_scope_references(connection, schema)
    active_team_references = sum(team_id_references.values()) + sum(team_scope_references.values())
    if active_team_references:
        hard_blockers.append(
            {
                "code": "active_team_references",
                "messageZh": "仍有 team_id 或 team scope 数据，不能删除 Team。",
                "count": active_team_references,
            }
        )

    users_without_roles = 0
    if (
        await _table_exists(connection, schema, "users")
        and await _table_exists(connection, schema, "user_roles")
        and await _table_exists(connection, schema, "roles")
    ):
        users_without_roles = await _count(
            connection,
            f"""
            SELECT COUNT(*)
            FROM {_quote_ident(schema)}.users AS app_user
            WHERE app_user.deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM {_quote_ident(schema)}.user_roles AS assignment
                  JOIN {_quote_ident(schema)}.roles AS role_row ON role_row.id = assignment.role_id
                  WHERE assignment.user_id = app_user.id
                    AND role_row.deleted_at IS NULL
                    AND role_row.is_active IS TRUE
              )
            """,
        )
    if users_without_roles:
        hard_blockers.append(
            {
                "code": "active_users_without_roles",
                "messageZh": "存在没有有效 UserRole 的在职员工，不能删除 users.role。",
                "count": users_without_roles,
            }
        )

    legacy_role_values: dict[str, int] = {}
    if await _column_exists(connection, schema, "users", "role"):
        role_rows = await connection.fetch(
            f"SELECT COALESCE(role, '<NULL>') AS role_value, COUNT(*) AS row_count "
            f"FROM {_quote_ident(schema)}.users GROUP BY COALESCE(role, '<NULL>') ORDER BY role_value"
        )
        legacy_role_values = {str(row["role_value"]): int(row["row_count"]) for row in role_rows}
        unsupported_roles = sum(
            count for role, count in legacy_role_values.items() if role not in {"member"}
        )
        if unsupported_roles:
            hard_blockers.append(
                {
                    "code": "legacy_user_role_values",
                    "messageZh": "users.role 仍含 member 之外的值，必须先核对其 UserRole 映射。",
                    "count": unsupported_roles,
                }
            )

    legacy_agent_payloads = {
        column: await _legacy_payload_count(connection, schema, "agents", column)
        for column in ("workflow", "judge_config", "rag_collection_id", "judge_template_id")
    }
    legacy_run_payloads = {
        column: await _legacy_payload_count(connection, schema, "agent_runs", column)
        for column in ("messages", "steps", "judge_score")
    }
    legacy_payload_total = sum(legacy_agent_payloads.values()) + sum(legacy_run_payloads.values())
    if legacy_payload_total:
        hard_blockers.append(
            {
                "code": "legacy_agent_payloads",
                "messageZh": "Agent 或 AgentRun 的待删除字段仍有数据，必须先归档或迁移。",
                "count": legacy_payload_total,
            }
        )

    extension_object_references = 0
    if await _column_exists(connection, schema, "platform_extension_sources", "artifact_ref"):
        extension_object_references = await _count(
            connection,
            f"SELECT COUNT(*) FROM {_quote_ident(schema)}.platform_extension_sources "
            "WHERE artifact_ref IS NOT NULL AND btrim(artifact_ref) <> ''",
        )

    connector_calls = 0
    connector_last_call = None
    if await _table_exists(connection, schema, "tool_call_logs"):
        connector_calls = await _count(
            connection,
            f"SELECT COUNT(*) FROM {_quote_ident(schema)}.tool_call_logs "
            "WHERE connector_id IS NOT NULL OR endpoint_id IS NOT NULL",
        )
        connector_last_call = await connection.fetchval(
            f"SELECT MAX(created_at) FROM {_quote_ident(schema)}.tool_call_logs "
            "WHERE connector_id IS NOT NULL OR endpoint_id IS NOT NULL"
        )

    active_legacy_bindings = 0
    if inventory["enterprise_application_tool_bindings"]["present"]:
        clauses: list[str] = []
        if await _column_exists(connection, schema, "enterprise_application_tool_bindings", "deleted_at"):
            clauses.append("deleted_at IS NULL")
        if await _column_exists(connection, schema, "enterprise_application_tool_bindings", "is_active"):
            clauses.append("is_active IS TRUE")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        active_legacy_bindings = await _count(
            connection,
            f"SELECT COUNT(*) FROM {_quote_ident(schema)}.enterprise_application_tool_bindings{where}",
        )
    if active_legacy_bindings:
        hard_blockers.append(
            {
                "code": "active_legacy_application_bindings",
                "messageZh": "仍有有效的旧应用工具绑定，必须先完成 Manifest Action 对照迁移。",
                "count": active_legacy_bindings,
            }
        )

    nonempty_retired_tables = {
        table: item["rowCount"]
        for table, item in inventory.items()
        if item["present"] and item["rowCount"] > 0
    }
    revision = None
    if await _table_exists(connection, schema, "alembic_version"):
        revision = await connection.fetchval(
            f"SELECT version_num FROM {_quote_ident(schema)}.alembic_version LIMIT 1"
        )
    database_now = await connection.fetchval("SELECT CURRENT_TIMESTAMP")
    return {
        "formatVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "databaseNow": database_now.isoformat(),
        "alembicRevision": revision,
        "schema": schema,
        "gates": {
            "runtimeDependenciesReady": not hard_blockers,
            "retiredDataArchiveRequired": bool(nonempty_retired_tables),
            "destructiveContractReady": not hard_blockers and not nonempty_retired_tables,
        },
        "hardBlockers": hard_blockers,
        "retiredTables": inventory,
        "nonemptyRetiredTablesRequiringArchive": nonempty_retired_tables,
        "foreignKeyDependencies": foreign_keys,
        "viewDependencies": view_dependencies,
        "evidence": {
            "activeDshRuns": active_dsh_runs,
            "teamIdReferences": team_id_references,
            "teamScopeReferences": team_scope_references,
            "activeUsersWithoutValidRole": users_without_roles,
            "legacyUserRoleValues": legacy_role_values,
            "legacyAgentPayloads": legacy_agent_payloads,
            "legacyAgentRunPayloads": legacy_run_payloads,
            "platformExtensionObjectReferences": extension_object_references,
            "activeLegacyApplicationBindings": active_legacy_bindings,
            "historicalConnectorCallCount": connector_calls,
            "connectorLastCallAt": connector_last_call.isoformat() if connector_last_call else None,
        },
        "manualChecks": [
            "在写 contract 迁移前，用代码搜索确认 ORM、API、后台任务和工具注册均不再引用待退役对象。",
            "对所有非空退役表生成独立归档并记录行数与 SHA-256；本脚本不会把非空表当作可直接删除。",
            "导出 platform_extension_sources.artifact_ref 对象清单，确认与工作空间 OSS 引用无交集。",
            "确认 tool_call_logs 不再被已退役的产品监控消费，再退役该条件表。",
            "保存受保护数据快照、Schema 指纹、pg_dump 校验值和对应不可变镜像 digest。",
        ],
    }


async def _run(args: argparse.Namespace) -> int:
    raw_url = args.database_url or os.getenv("DATABASE_URL", "")
    if not raw_url:
        print("缺少 DATABASE_URL 或 --database-url。", file=sys.stderr)
        return 2
    try:
        _assert_connection_scope(raw_url, allow_remote=args.allow_remote_read_only)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    connection = await asyncpg.connect(_database_url(raw_url), timeout=args.connect_timeout)
    try:
        async with connection.transaction(readonly=True, isolation="repeatable_read"):
            await connection.execute("SELECT set_config('statement_timeout', $1, true)", str(args.statement_timeout_ms))
            report = await build_report(connection, schema=args.schema)
    finally:
        await connection.close()

    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).resolve()
        if output.exists() and not args.overwrite:
            print(f"输出文件已存在，拒绝覆盖：{output}", file=sys.stderr)
            return 2
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"已写入退役表 preflight 报告：{output}")
    else:
        print(rendered, end="")
    return 0 if report["gates"][args.require_gate] else 3


def main() -> int:
    parser = argparse.ArgumentParser(description="只读检查待退役表、字段和运行时数据库依赖")
    parser.add_argument("--database-url", help="PostgreSQL URL；建议通过 DATABASE_URL 提供")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--output", help="JSON 报告路径；省略时输出到 stdout")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有报告")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--statement-timeout-ms", type=int, default=120_000)
    parser.add_argument("--allow-remote-read-only", action="store_true")
    parser.add_argument(
        "--require-gate",
        choices=("runtimeDependenciesReady", "destructiveContractReady"),
        default="destructiveContractReady",
    )
    args = parser.parse_args()
    if args.statement_timeout_ms < 1:
        parser.error("--statement-timeout-ms 必须大于 0")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
