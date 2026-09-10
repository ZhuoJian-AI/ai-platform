#!/usr/bin/env python3
"""Capture a read-only, credential-free database preservation report.

The report contains exact row counts and deterministic hashes, never row data,
passwords, tokens, database URLs, or file bodies.  It is intended to be taken
before and after a contract migration and compared as release evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg

PROTECTED_TABLES = (
    "admins",
    "organizations",
    "organization_slug_aliases",
    "departments",
    "users",
    "roles",
    "role_permissions",
    "role_data_departments",
    "user_roles",
    "api_keys",
    "llm_providers",
    "model_deployments",
    "routing_policies",
    "dlp_rules",
    "ai_quota_events",
    "audit_logs",
    "workspaces",
    "workspace_folders",
    "workspace_files",
    "workspace_file_versions",
    "file_mutations",
    "workspace_file_event_outbox",
    "workspace_preview_jobs",
    "workspace_upload_sessions",
    "workspace_audit_events",
    "workspace_share_links",
    "memories",
    "tasks",
    "task_messages",
    "task_file_refs",
    "agent_runs",
    "agent_run_events",
    "agents",
    "enterprise_applications",
    "enterprise_application_grants",
    "enterprise_application_integrations",
    "enterprise_application_sso_codes",
    "enterprise_application_actions",
    "enterprise_application_action_requests",
    "enterprise_application_events",
    "enterprise_application_event_routes",
    "enterprise_application_event_deliveries",
    "ecs_runtimes",
    "ecs_module_releases",
    "multimodal_jobs",
    "voice_profiles",
    "voice_profile_grants",
    "voice_authorization_records",
)

_SCHEMA_QUERIES = {
    "relations": """
        SELECT format('%I.%I', namespace.nspname, rel.relname) AS identity,
               concat_ws('|', rel.relkind, rel.relpersistence, rel.relrowsecurity,
                         rel.relforcerowsecurity,
                         COALESCE(pg_get_partkeydef(rel.oid), '')) AS definition
        FROM pg_class AS rel
        JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
        WHERE namespace.nspname = $1 AND rel.relkind IN ('r', 'p', 'S')
        ORDER BY rel.relkind, rel.relname
    """,
    "columns": """
        SELECT format('%I.%I.%s', table_schema, table_name, ordinal_position) AS identity,
               concat_ws('|', column_name, udt_schema, udt_name, is_nullable,
                         COALESCE(column_default, ''), is_identity, identity_generation,
                         is_generated, COALESCE(generation_expression, '')) AS definition
        FROM information_schema.columns
        WHERE table_schema = $1
        ORDER BY table_name, ordinal_position
    """,
    "constraints": """
        SELECT format('%I.%I', rel.relname, constraint_row.conname) AS identity,
               pg_get_constraintdef(constraint_row.oid, true) AS definition
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS rel ON rel.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
        WHERE namespace.nspname = $1
          -- PostgreSQL 18 exposes NOT NULL entries in pg_constraint while
          -- older supported versions do not. Column nullability is already
          -- fingerprinted through information_schema.columns, so excluding
          -- them here avoids counting the same invariant twice and keeps the
          -- protected snapshot stable across PostgreSQL 16-18.
          AND constraint_row.contype <> 'n'
        ORDER BY rel.relname, constraint_row.conname
    """,
    "indexes": """
        SELECT format('%I.%I', table_row.relname, index_row.relname) AS identity,
               pg_get_indexdef(index_row.oid) AS definition
        FROM pg_index AS index_meta
        JOIN pg_class AS table_row ON table_row.oid = index_meta.indrelid
        JOIN pg_class AS index_row ON index_row.oid = index_meta.indexrelid
        JOIN pg_namespace AS namespace ON namespace.oid = table_row.relnamespace
        WHERE namespace.nspname = $1
        ORDER BY table_row.relname, index_row.relname
    """,
    "triggers": """
        SELECT format('%I.%I', rel.relname, trigger_row.tgname) AS identity,
               pg_get_triggerdef(trigger_row.oid, true) AS definition
        FROM pg_trigger AS trigger_row
        JOIN pg_class AS rel ON rel.oid = trigger_row.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
        WHERE namespace.nspname = $1 AND NOT trigger_row.tgisinternal
        ORDER BY rel.relname, trigger_row.tgname
    """,
    "views": """
        SELECT format('%I.%I', namespace.nspname, rel.relname) AS identity,
               concat(rel.relkind, '|', pg_get_viewdef(rel.oid, true)) AS definition
        FROM pg_class AS rel
        JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
        WHERE namespace.nspname = $1 AND rel.relkind IN ('v', 'm')
        ORDER BY rel.relkind, rel.relname
    """,
    "functions": """
        SELECT format('%I.%I(%s)', namespace.nspname, procedure.proname,
                      pg_get_function_identity_arguments(procedure.oid)) AS identity,
               pg_get_functiondef(procedure.oid) AS definition
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = $1 AND procedure.prokind IN ('f', 'p')
        ORDER BY procedure.proname, pg_get_function_identity_arguments(procedure.oid)
    """,
    "extensions": """
        SELECT extension.extname AS identity,
               concat(extension.extversion, '|', namespace.nspname) AS definition
        FROM pg_extension AS extension
        JOIN pg_namespace AS namespace ON namespace.oid = extension.extnamespace
        ORDER BY extension.extname
    """,
    "row_security_policies": """
        SELECT format('%I.%I.%I', schemaname, tablename, policyname) AS identity,
               concat_ws('|', permissive, roles::text, cmd, COALESCE(qual, ''),
                         COALESCE(with_check, '')) AS definition
        FROM pg_policies
        WHERE schemaname = $1
        ORDER BY tablename, policyname
    """,
}


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


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _digest_records(records: Iterable[Mapping[str, Any]]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for record in records:
        payload = json.dumps(_json_value(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        encoded = payload.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return digest.hexdigest(), count


async def _table_exists(connection: asyncpg.Connection, schema: str, table: str) -> bool:
    return bool(await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.{table}"))


async def _primary_key_columns(
    connection: asyncpg.Connection,
    schema: str,
    table: str,
) -> list[str]:
    rows = await connection.fetch(
        """
        SELECT attribute.attname
        FROM pg_index AS index_row
        JOIN pg_class AS rel ON rel.oid = index_row.indrelid
        JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = rel.oid
         AND attribute.attnum = ANY(index_row.indkey)
        WHERE namespace.nspname = $1
          AND rel.relname = $2
          AND index_row.indisprimary
        ORDER BY array_position(index_row.indkey, attribute.attnum)
        """,
        schema,
        table,
    )
    return [str(row["attname"]) for row in rows]


async def _excluded_large_columns(
    connection: asyncpg.Connection,
    schema: str,
    table: str,
) -> list[str]:
    rows = await connection.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = $1
          AND table_name = $2
          AND (data_type = 'bytea' OR udt_name = 'vector')
        ORDER BY ordinal_position
        """,
        schema,
        table,
    )
    return [str(row["column_name"]) for row in rows]


async def _fingerprint_table(
    connection: asyncpg.Connection,
    schema: str,
    table: str,
) -> dict[str, Any]:
    if not await _table_exists(connection, schema, table):
        return {"present": False, "rowCount": 0}

    row_count = int(
        await connection.fetchval(f"SELECT COUNT(*) FROM {_quote_ident(schema)}.{_quote_ident(table)}")
        or 0
    )
    primary_key = await _primary_key_columns(connection, schema, table)
    excluded_columns = await _excluded_large_columns(connection, schema, table)
    if not primary_key:
        return {
            "present": True,
            "rowCount": row_count,
            "fingerprintStatus": "missing_primary_key",
            "excludedLargeColumns": excluded_columns,
        }

    key_expression = ", ".join(f"row_data.{_quote_ident(column)}" for column in primary_key)
    order_expression = ", ".join(
        f"row_data.{_quote_ident(column)} NULLS FIRST" for column in primary_key
    )
    query = (
        f"SELECT jsonb_build_array({key_expression})::text AS key_data, "
        "(to_jsonb(row_data) - $1::text[])::text AS content_data "
        f"FROM {_quote_ident(schema)}.{_quote_ident(table)} AS row_data "
        f"ORDER BY {order_expression}"
    )
    key_digest = hashlib.sha256()
    content_digest = hashlib.sha256()
    streamed_count = 0
    async for row in connection.cursor(query, excluded_columns, prefetch=500):
        key_bytes = str(row["key_data"]).encode("utf-8")
        content_bytes = str(row["content_data"]).encode("utf-8")
        key_digest.update(len(key_bytes).to_bytes(8, "big"))
        key_digest.update(key_bytes)
        content_digest.update(len(content_bytes).to_bytes(8, "big"))
        content_digest.update(content_bytes)
        streamed_count += 1
    if streamed_count != row_count:
        raise RuntimeError(f"{schema}.{table} 在快照期间发生变化")
    return {
        "present": True,
        "rowCount": row_count,
        "primaryKeyColumns": primary_key,
        "primaryKeySha256": key_digest.hexdigest(),
        "contentSha256": content_digest.hexdigest(),
        "excludedLargeColumns": excluded_columns,
        "fingerprintStatus": "complete",
    }


async def _schema_fingerprint(connection: asyncpg.Connection, schema: str) -> dict[str, Any]:
    categories: dict[str, Any] = {}
    overall = hashlib.sha256()
    for category, query in _SCHEMA_QUERIES.items():
        rows = await connection.fetch(query, schema) if "$1" in query else await connection.fetch(query)
        items: list[dict[str, str]] = []
        for row in rows:
            definition_hash = hashlib.sha256(str(row["definition"]).encode("utf-8")).hexdigest()
            items.append({"identity": str(row["identity"]), "definitionSha256": definition_hash})
        category_hash, count = _digest_records(items)
        categories[category] = {"count": count, "sha256": category_hash, "items": items}
        overall.update(category.encode("utf-8"))
        overall.update(category_hash.encode("ascii"))
    return {"sha256": overall.hexdigest(), "categories": categories}


async def build_report(
    connection: asyncpg.Connection,
    *,
    schema: str,
    protected_tables: Iterable[str] = PROTECTED_TABLES,
) -> dict[str, Any]:
    database_now = await connection.fetchval("SELECT CURRENT_TIMESTAMP")
    database_name = await connection.fetchval("SELECT current_database()")
    revision = None
    if await _table_exists(connection, schema, "alembic_version"):
        revision = await connection.fetchval(
            f"SELECT version_num FROM {_quote_ident(schema)}.alembic_version LIMIT 1"
        )
    table_reports: dict[str, Any] = {}
    for table in protected_tables:
        table_reports[table] = await _fingerprint_table(connection, schema, table)
    return {
        "formatVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "databaseNow": database_now.isoformat(),
        "databaseName": database_name,
        "schema": schema,
        "alembicRevision": revision,
        "schemaFingerprint": await _schema_fingerprint(connection, schema),
        "protectedTables": table_reports,
        "missingProtectedTables": [
            table for table, item in table_reports.items() if not item["present"]
        ],
        "externalVerificationRequired": [
            "对 workspace_files.content_ref 与 workspace_file_versions.content_ref "
            "执行对象存储存在性抽样；本数据库脚本不持有 OSS 凭据。",
            "同时保存 pg_dump/pg_restore --list 校验结果以及 Backend、Frontend、Worker 镜像 digest。",
        ],
        "notes": [
            "报告不包含数据库连接串、凭据或原始行数据。",
            "bytea 与 vector 列不进入内容哈希；其引用、大小和业务内容列仍被校验。",
            "部署前后应比较 rowCount、primaryKeySha256、contentSha256 与 schemaFingerprint。",
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
        print(f"已写入受保护数据快照：{output}")
    else:
        print(rendered, end="")
    if args.fail_on_missing and report["missingProtectedTables"]:
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成只读受保护数据快照与 PostgreSQL Schema 指纹")
    parser.add_argument("--database-url", help="PostgreSQL URL；建议通过 DATABASE_URL 提供")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--output", help="JSON 报告路径；省略时输出到 stdout")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有报告")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--statement-timeout-ms", type=int, default=300_000)
    parser.add_argument("--allow-remote-read-only", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args()
    if args.statement_timeout_ms < 1:
        parser.error("--statement-timeout-ms 必须大于 0")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
