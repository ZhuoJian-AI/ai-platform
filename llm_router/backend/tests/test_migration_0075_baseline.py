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
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ai_infra:ai_infra@127.0.0.1:5434/ai_infra_test"
)
EXPECTED_SQL_SHA256 = "e2a69cdbed3cc7ab3b8dcb2cc32003c5a947e4a194263179ae9182ecbbea39f6"
EXPECTED_SCHEMA_SHA256 = "cc0e33965fe10b6029e0356bd76401b62154e2fb8eb822262bbd3d07a6354cb1"
EXPECTED_SCHEMA_CATEGORIES = {
    "columns": (672, "232db02b65059a29ffcf14ed05dd10ae1f40f5f92577593b96a4a37fb3ba2258"),
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
    raw_url = (
        os.getenv("MIGRATION_TEST_DATABASE_URL")
        or os.getenv("TEST_DATABASE_URL")
        or DEFAULT_TEST_DATABASE_URL
    )
    url = make_url(raw_url).set(drivername="postgresql+asyncpg")
    if url.get_backend_name() != "postgresql" or not url.database:
        pytest.fail("迁移回归测试只允许使用 PostgreSQL 测试数据库")
    if "test" not in url.database.lower():
        pytest.fail("迁移回归数据库名称必须包含 test，避免误连接业务数据库")
    host = (url.host or "").strip("[]").lower()
    if host not in {"localhost", "127.0.0.1", "::1"} and os.getenv(
        "MIGRATION_TEST_ALLOW_REMOTE"
    ) != "1":
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
        await maintenance.execute(
            f"CREATE DATABASE {quoted_database} TEMPLATE template0 ENCODING 'UTF8'"
        )
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
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
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
    assert 'down_revision = None' in migration_source
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
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
        ) == 0
        assert await connection.fetchval(
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
        ) == 0
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND "
            "((table_name = 'agents' AND column_name = ANY($1::text[])) OR "
            " (table_name = 'memories' AND column_name = 'embedding'))",
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
        ) == 0
        assert await connection.fetchval(
            "SELECT to_regclass('public.ai_quota_monthly_rollups')::text"
        ) == "ai_quota_monthly_rollups"
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM pg_proc WHERE proname IN "
            "('reject_ai_quota_event_mutation', 'reject_new_usd_budget_cap')"
        ) == 2
        assert await connection.fetchval(
            "SELECT COUNT(*) FROM pg_trigger "
            "WHERE tgname = 'trg_ai_quota_events_append_only' AND NOT tgisinternal"
        ) == 1

        fingerprint = await SNAPSHOT._schema_fingerprint(connection, "public")
        assert fingerprint["sha256"] == EXPECTED_SCHEMA_SHA256
        assert {
            name: (details["count"], details["sha256"])
            for name, details in fingerprint["categories"].items()
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
        assert (await SNAPSHOT._schema_fingerprint(connection, "public"))["sha256"] == (
            EXPECTED_SCHEMA_SHA256
        )
    finally:
        await connection.close()

    checked = _invoke_alembic(migration_database_url, "check")
    assert checked.returncode == 0, f"{checked.stdout}\n{checked.stderr}"
    assert "No new upgrade operations detected" in f"{checked.stdout}\n{checked.stderr}"
