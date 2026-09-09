"""Real PostgreSQL verification for the compact 0075/0076 schema baseline."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"
BASELINE_MIGRATION = VERSIONS_DIR / "0075_retired_schema_contract.py"
BASELINE_SQL = VERSIONS_DIR / "0075_schema_baseline.sql"
DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://ai_infra:ai_infra@127.0.0.1:5434/ai_infra_test"
EXPECTED_SQL_SHA256 = "b0fc1bc253ad9734d68f561b0c15368a05787eb9e86ba5c6b49de367337c4a38"
EXPECTED_SCHEMA_SHA256 = "eb3ceb8802daf268996c81007fa2b8d34d6bd3c0f8b49e6981dc18ba0ec14033"
EXPECTED_SCHEMA_CATEGORIES = {
    "columns": (671, "e71d9a8c44d0de62a0c69ddaae03b8c3d2b7c900df6eaf8ba88c43f09c96c553"),
    "constraints": (680, "034b93267f8ad5e44d56fa539e2baea2f87a943d59bcac444a1d9591be5c27a8"),
    "extensions": (1, "c9462b51547b30b2988ac202f0f666df58a79ca58f1468921122f4505ad7a3d3"),
    "functions": (2, "91b13a067d341bd9df13a123070fe64327a24a6ab4e5745ea80b3d3005b02108"),
    "indexes": (224, "aff5de8092ff1d37ff2c6178b50cafb381af8af9d244f3339ed47e30450d3502"),
    "relations": (54, "81599bdbd94a2c55d5e47621ed74731c21bdfd2df20470e1f51dd6045d70d840"),
    "row_security_policies": (
        0,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ),
    "triggers": (4, "9953d3c7b7847f052cc05d627120688d50091489fcdcf4acee4cd70863b4d3ef"),
    "views": (1, "4f940fada252a86f5b41417920cd57dd02079611eaa781dc0312d681e59790bf"),
}


@pytest_asyncio.fixture(autouse=True)
async def db_engine() -> AsyncIterator[None]:
    """Disable the create-all fixture; this module owns a migrated database."""

    yield None


def _load_snapshot_script() -> ModuleType:
    path = REPOSITORY_ROOT / "scripts" / "capture_protected_database_snapshot.py"
    spec = importlib.util.spec_from_file_location("baseline_snapshot_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SNAPSHOT = _load_snapshot_script()


def _configured_database_url() -> tuple[URL, bool]:
    explicit = bool(os.getenv("MIGRATION_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL"))
    raw_url = os.getenv("MIGRATION_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
    url = make_url(raw_url).set(drivername="postgresql+asyncpg")
    if url.get_backend_name() != "postgresql" or not url.database:
        pytest.fail("迁移回归测试只允许使用 PostgreSQL 测试数据库")
    if "test" not in url.database.lower():
        pytest.fail("迁移回归数据库名称必须包含 test，避免误连接业务数据库")
    host = (url.host or "").strip("[]").lower()
    if host not in {"localhost", "127.0.0.1", "::1"} and os.getenv("MIGRATION_TEST_ALLOW_REMOTE") != "1":
        pytest.fail("远端迁移测试必须显式设置 MIGRATION_TEST_ALLOW_REMOTE=1")
    return url, explicit


def _asyncpg_connect_kwargs(url: URL, *, database: str) -> dict[str, object]:
    return {
        "host": url.host or "127.0.0.1",
        "port": url.port or 5432,
        "user": url.username,
        "password": url.password,
        "database": database,
    }


def _ephemeral_database_url(base: URL, database: str) -> str:
    return base.set(database=database).render_as_string(hide_password=False)


def _invoke_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"APP_ENV": "test", "DATABASE_URL": database_url})
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest_asyncio.fixture
async def migration_database_url() -> AsyncIterator[str]:
    base_url, explicit_url = _configured_database_url()
    maintenance_database = os.getenv("MIGRATION_TEST_MAINTENANCE_DATABASE", "postgres")
    database_name = f"{base_url.database[:40]}_baseline_{uuid4().hex[:12]}"
    if not re.fullmatch(r"[A-Za-z0-9_]+", database_name):
        pytest.fail("临时迁移数据库名称包含不安全字符")

    try:
        maintenance = await asyncpg.connect(
            **_asyncpg_connect_kwargs(base_url, database=maintenance_database),
            timeout=5,
        )
    except (OSError, asyncpg.PostgresError) as exc:
        required = explicit_url or os.getenv("REQUIRE_REAL_POSTGRES_MIGRATION_TESTS") == "1"
        if required:
            pytest.fail(f"无法连接真实 PostgreSQL 迁移测试实例：{type(exc).__name__}")
        pytest.skip("本机没有可用的 PostgreSQL 迁移测试实例")

    quoted_database = '"' + database_name.replace('"', '""') + '"'
    try:
        await maintenance.execute(f"CREATE DATABASE {quoted_database} TEMPLATE template0 ENCODING 'UTF8'")
    finally:
        await maintenance.close()

    database_url = _ephemeral_database_url(base_url, database_name)
    try:
        yield database_url
    finally:
        maintenance = await asyncpg.connect(
            **_asyncpg_connect_kwargs(base_url, database=maintenance_database),
            timeout=5,
        )
        try:
            await maintenance.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await maintenance.execute(f"DROP DATABASE IF EXISTS {quoted_database}")
        finally:
            await maintenance.close()


def test_compact_baseline_and_retirement_contract_are_the_only_revisions() -> None:
    assert sorted(path.name for path in VERSIONS_DIR.glob("*.py")) == [
        "0075_retired_schema_contract.py",
        "0076_retire_rag_and_user_skills.py",
    ]
    migration_source = BASELINE_MIGRATION.read_text(encoding="utf-8")
    assert "down_revision = None" in migration_source
    assert "Base.metadata" not in migration_source
    assert "create_all" not in migration_source
    assert hashlib.sha256(BASELINE_SQL.read_bytes()).hexdigest() == EXPECTED_SQL_SHA256


@pytest.mark.asyncio
async def test_empty_postgresql_installs_exact_current_schema_and_remains_noop(
    migration_database_url: str,
) -> None:
    installed = _invoke_alembic(migration_database_url, "upgrade", "head")
    assert installed.returncode == 0, f"{installed.stdout}\n{installed.stderr}"

    raw_url = make_url(migration_database_url)
    connect_kwargs = _asyncpg_connect_kwargs(raw_url, database=raw_url.database or "")
    connection = await asyncpg.connect(**connect_kwargs, timeout=5)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "0076_retire_rag_and_user_skills"
        )
        assert await connection.fetchval("SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'") == 0
        assert (
            await connection.fetchval(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY($1::text[])",
                [
                    "rag_collections",
                    "rag_folders",
                    "rag_documents",
                    "rag_chunks",
                    "skill_folders",
                    "skill_files",
                    "skill_versions",
                    "skill_executions",
                ],
            )
            == 0
        )
        assert (
            await connection.fetchval(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = 'public' AND "
                "((table_name = 'agents' AND column_name = ANY($1::text[])) OR "
                " (table_name = 'memories' AND column_name = 'embedding') OR "
                " (table_name = 'model_deployments' AND column_name = 'embedding_dimensions'))",
                [
                    "model_alias",
                    "memory_config",
                    "workspace_id",
                    "rag_collection_ids",
                    "skill_ids",
                    "application_id",
                    "module_key",
                    "page_key",
                    "temperature",
                    "max_tokens",
                ],
            )
            == 0
        )
        assert (
            await connection.fetchval("SELECT to_regclass('public.ai_quota_monthly_rollups')::text")
            == "ai_quota_monthly_rollups"
        )
        assert (
            await connection.fetchval(
                "SELECT COUNT(*) FROM pg_proc WHERE proname IN "
                "('reject_ai_quota_event_mutation', 'reject_new_usd_budget_cap')"
            )
            == 2
        )
        assert (
            await connection.fetchval(
                "SELECT COUNT(*) FROM pg_trigger WHERE tgname = 'trg_ai_quota_events_append_only' AND NOT tgisinternal"
            )
            == 1
        )

        fingerprint = await SNAPSHOT._schema_fingerprint(connection, "public")
        assert fingerprint["sha256"] == EXPECTED_SCHEMA_SHA256
        assert {
            name: (details["count"], details["sha256"]) for name, details in fingerprint["categories"].items()
        } == EXPECTED_SCHEMA_CATEGORIES
        relation_storage_before = await connection.fetch(
            """
            SELECT namespace.nspname, relation.relname, relation.relkind,
                   relation.oid, relation.relfilenode
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
            ORDER BY relation.relkind, relation.relname
            """
        )
    finally:
        await connection.close()

    repeated = _invoke_alembic(migration_database_url, "upgrade", "head")
    assert repeated.returncode == 0, f"{repeated.stdout}\n{repeated.stderr}"

    connection = await asyncpg.connect(**connect_kwargs, timeout=5)
    try:
        relation_storage_after = await connection.fetch(
            """
            SELECT namespace.nspname, relation.relname, relation.relkind,
                   relation.oid, relation.relfilenode
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
            ORDER BY relation.relkind, relation.relname
            """
        )
        assert relation_storage_after == relation_storage_before
        assert (await SNAPSHOT._schema_fingerprint(connection, "public"))["sha256"] == (EXPECTED_SCHEMA_SHA256)
    finally:
        await connection.close()

    checked = _invoke_alembic(migration_database_url, "check")
    assert checked.returncode == 0, f"{checked.stdout}\n{checked.stderr}"
    assert "No new upgrade operations detected" in f"{checked.stdout}\n{checked.stderr}"


@pytest.mark.asyncio
async def test_embedding_deployments_and_legacy_selectors_are_retired(
    migration_database_url: str,
) -> None:
    installed = _invoke_alembic(migration_database_url, "upgrade", "0075_retired_schema_contract")
    assert installed.returncode == 0, f"{installed.stdout}\n{installed.stderr}"

    raw_url = make_url(migration_database_url)
    connect_kwargs = _asyncpg_connect_kwargs(raw_url, database=raw_url.database or "")
    connection = await asyncpg.connect(**connect_kwargs, timeout=5)
    organization_id = uuid4()
    provider_id = uuid4()
    api_key_id = uuid4()
    try:
        await connection.execute(
            """
            INSERT INTO organizations (id, name, slug, settings)
            VALUES ($1, 'Embedding 迁移企业', $2, '{}'::jsonb)
            """,
            organization_id,
            f"embedding-retire-{organization_id.hex[:8]}",
        )
        await connection.execute(
            """
            INSERT INTO llm_providers (
                id, organization_id, name, vendor, provider_type, base_url,
                api_key_encrypted, api_key_version, scope_type, is_active,
                priority, weight, timeout_seconds, max_retries,
                supported_models, health_status, config
            ) VALUES (
                $1, $2, '迁移供应商', 'custom', 'openai', 'https://example.com/v1',
                'encrypted-placeholder', 1, 'organization', TRUE,
                0, 1, 120, 2,
                '["chat-model", "text-embedding-v4", "legacy-hybrid"]'::jsonb,
                'unknown', '{}'::jsonb
            )
            """,
            provider_id,
            organization_id,
        )
        await connection.execute(
            """
            INSERT INTO model_deployments (
                id, provider_id, model_id, adapter, capabilities
            ) VALUES
                ($1, $4, 'chat-model', 'openai_chat_completions', '["chat"]'::jsonb),
                ($2, $4, 'text-embedding-v4', 'openai_embeddings', '["embedding"]'::jsonb),
                ($3, $4, 'legacy-hybrid', 'openai_chat_completions', '["chat", "embedding"]'::jsonb)
            """,
            uuid4(),
            uuid4(),
            uuid4(),
            provider_id,
        )
        await connection.execute(
            """
            INSERT INTO api_keys (
                id, key_prefix, key_hash, key_encrypted, key_name, scope_type,
                organization_id, allowed_models, is_active
            ) VALUES (
                $1, 'e2e_embed', $2, '', 'Embedding 迁移 Key', 'organization',
                $3, '["chat-model", "text-embedding-v4", "legacy-hybrid"]'::jsonb, TRUE
            )
            """,
            api_key_id,
            uuid4().hex,
            organization_id,
        )
    finally:
        await connection.close()

    upgraded = _invoke_alembic(migration_database_url, "upgrade", "head")
    assert upgraded.returncode == 0, f"{upgraded.stdout}\n{upgraded.stderr}"

    connection = await asyncpg.connect(**connect_kwargs, timeout=5)
    try:
        deployments = await connection.fetch(
            """
            SELECT model_id, capabilities
            FROM model_deployments
            WHERE provider_id = $1
            ORDER BY model_id
            """,
            provider_id,
        )
        assert [(row["model_id"], row["capabilities"]) for row in deployments] == [
            ("chat-model", '["chat"]'),
            ("legacy-hybrid", '["chat"]'),
        ]
        assert await connection.fetchval(
            "SELECT supported_models FROM llm_providers WHERE id = $1", provider_id
        ) == '["chat-model", "legacy-hybrid"]'
        assert await connection.fetchval(
            "SELECT allowed_models FROM api_keys WHERE id = $1", api_key_id
        ) == '["chat-model", "legacy-hybrid"]'
        assert await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'model_deployments'
              AND column_name = 'embedding_dimensions'
            """
        ) == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_role_scoped_personas_become_private_without_losing_prompts(
    migration_database_url: str,
) -> None:
    installed = _invoke_alembic(migration_database_url, "upgrade", "0075_retired_schema_contract")
    assert installed.returncode == 0, f"{installed.stdout}\n{installed.stderr}"

    raw_url = make_url(migration_database_url)
    connect_kwargs = _asyncpg_connect_kwargs(raw_url, database=raw_url.database or "")
    connection = await asyncpg.connect(**connect_kwargs, timeout=5)
    organization_id = uuid4()
    creator_id = uuid4()
    role_id = uuid4()
    private_agent_id = uuid4()
    orphan_agent_id = uuid4()
    existing_agent_id = uuid4()
    try:
        await connection.execute(
            """
            INSERT INTO organizations (id, name, slug, settings)
            VALUES ($1, '迁移测试企业', $2, '{}'::jsonb)
            """,
            organization_id,
            f"migration-{organization_id.hex[:8]}",
        )
        await connection.execute(
            """
            INSERT INTO users (id, organization_id, username, is_active)
            VALUES ($1, $2, 'legacy-creator', TRUE)
            """,
            creator_id,
            organization_id,
        )
        await connection.execute(
            """
            INSERT INTO roles (id, organization_id, name, code, data_scope)
            VALUES ($1, $2, '旧角色', 'legacy-role', 'self')
            """,
            role_id,
            organization_id,
        )
        await connection.execute(
            """
            INSERT INTO agents (
                id, organization_id, name, slug, system_prompt, scope_type,
                scope_id, created_by, is_active
            ) VALUES
                ($1, $2, '已有个人角色', 'shared-name', '已有提示词', 'user', $3, $3, TRUE),
                ($4, $2, '旧角色智能体', 'shared-name', '必须保留的提示词', 'role', $5, $3, TRUE),
                ($6, $2, '无创建者智能体', 'orphan', '孤儿提示词', 'role', $5, NULL, TRUE)
            """,
            existing_agent_id,
            organization_id,
            str(creator_id),
            private_agent_id,
            str(role_id),
            orphan_agent_id,
        )
    finally:
        await connection.close()

    upgraded = _invoke_alembic(migration_database_url, "upgrade", "head")
    assert upgraded.returncode == 0, f"{upgraded.stdout}\n{upgraded.stderr}"

    connection = await asyncpg.connect(**connect_kwargs, timeout=5)
    try:
        private_agent = await connection.fetchrow(
            """
            SELECT scope_type, scope_id, slug, system_prompt, is_active
            FROM agents WHERE id = $1
            """,
            private_agent_id,
        )
        assert private_agent is not None
        assert private_agent["scope_type"] == "user"
        assert private_agent["scope_id"] == str(creator_id)
        assert private_agent["slug"].startswith("shared-name-legacy-")
        assert private_agent["system_prompt"] == "必须保留的提示词"
        assert private_agent["is_active"] is True

        orphan_agent = await connection.fetchrow(
            """
            SELECT scope_type, scope_id, system_prompt, is_active
            FROM agents WHERE id = $1
            """,
            orphan_agent_id,
        )
        assert orphan_agent is not None
        assert orphan_agent["scope_type"] == "organization"
        assert orphan_agent["scope_id"] is None
        assert orphan_agent["system_prompt"] == "孤儿提示词"
        assert orphan_agent["is_active"] is False
        assert await connection.fetchval("SELECT COUNT(*) FROM agents WHERE scope_type = 'role'") == 0
    finally:
        await connection.close()
