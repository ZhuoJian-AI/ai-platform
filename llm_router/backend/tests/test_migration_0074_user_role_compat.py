"""Real-PostgreSQL regression coverage for the 0073 -> 0074 user compatibility fix."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from app.api.users import _user_integrity_http_error
from app.auth.admin_auth import CurrentAdmin, require_admin, require_org_access_write
from app.database import get_db
from app.main import app
from app.models.admin import Admin
from app.models.organization import Organization
from app.models.user import User
from app.utils.integrity_errors import classify_integrity_error
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ai_infra:ai_infra@127.0.0.1:5434/ai_infra_test"
)


@pytest_asyncio.fixture(autouse=True)
async def db_engine() -> AsyncIterator[None]:
    """Disable the create_all fixture; this module owns a migrated database."""

    yield None


def _configured_database_url() -> tuple[URL, bool]:
    explicit = bool(os.getenv("MIGRATION_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL"))
    raw_url = (
        os.getenv("MIGRATION_TEST_DATABASE_URL")
        or os.getenv("TEST_DATABASE_URL")
        or DEFAULT_TEST_DATABASE_URL
    )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or not url.database:
        pytest.fail("迁移回归测试只允许使用 PostgreSQL 测试数据库")
    url = url.set(drivername="postgresql+asyncpg")
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


def _run_alembic(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env.update({"APP_ENV": "test", "DATABASE_URL": database_url})
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"Alembic upgrade {revision} 失败。\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


@pytest_asyncio.fixture
async def migration_database_url() -> AsyncIterator[str]:
    base_url, explicit_url = _configured_database_url()
    maintenance_database = os.getenv("MIGRATION_TEST_MAINTENANCE_DATABASE", "postgres")
    suffix = uuid4().hex[:12]
    database_name = f"{base_url.database[:40]}_migration_{suffix}"
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


@pytest.mark.asyncio
async def test_0073_to_0074_supports_employee_crud_and_precise_unique_diagnostics(
    migration_database_url: str,
) -> None:
    _run_alembic(migration_database_url, "0073_native_assistant_default")
    raw_url = make_url(migration_database_url)
    organization_id = uuid4()
    connection = await asyncpg.connect(
        **_asyncpg_connect_kwargs(raw_url, database=raw_url.database or ""),
        timeout=5,
    )
    try:
        before = await connection.fetchrow(
            """
            SELECT is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'role'
            """
        )
        assert before is not None
        assert before["is_nullable"] == "NO"
        assert before["column_default"] is None
    finally:
        await connection.close()

    pre_upgrade_engine = create_async_engine(migration_database_url, pool_pre_ping=True)
    pre_upgrade_factory = async_sessionmaker(pre_upgrade_engine, expire_on_commit=False)
    async with pre_upgrade_factory() as session:
        session.add(
            Organization(
                id=organization_id,
                name="迁移回归企业",
                slug=f"migration-{uuid4().hex[:8]}",
            )
        )
        await session.commit()
    async with pre_upgrade_factory() as session:
        session.add(
            User(
                organization_id=organization_id,
                username="pre-upgrade-user",
                password_hash="test-only",
            )
        )
        with pytest.raises(IntegrityError) as captured:
            await session.flush()
        pre_upgrade_failure = classify_integrity_error(captured.value)
        assert pre_upgrade_failure.sqlstate == "23502"
        assert pre_upgrade_failure.column_name == "role"
        await session.rollback()
    await pre_upgrade_engine.dispose()

    _run_alembic(migration_database_url, "0074_user_role_compat")
    connection = await asyncpg.connect(
        **_asyncpg_connect_kwargs(raw_url, database=raw_url.database or ""),
        timeout=5,
    )
    try:
        after = await connection.fetchrow(
            """
            SELECT is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'role'
            """
        )
        assert after is not None
        assert after["is_nullable"] == "NO"
        assert "member" in str(after["column_default"])
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
            "0074_user_role_compat"
        )
    finally:
        await connection.close()

    engine = create_async_engine(migration_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        admin = Admin(
            username=f"migration-admin-{uuid4().hex[:8]}",
            password_hash="test-only",
            role="platform_super_admin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        admin_auth = CurrentAdmin(
            admin=admin,
            id=admin.id,
            username=admin.username,
            role="platform_super_admin",
        )

    async def override_get_db() -> AsyncIterator[object]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_org_access_write] = lambda: admin_auth
    app.dependency_overrides[require_admin] = lambda: admin_auth
    payload = {"username": "migration-user", "password": "test-pass-123", "role": "member"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/api/v1/organizations/{organization_id}/users",
                json=payload,
            )
            assert created.status_code == 201, created.text
            first_user_id = UUID(created.json()["id"])

            updated = await client.patch(
                f"/api/v1/users/{first_user_id}",
                json={"display_name": "迁移回归员工"},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["display_name"] == "迁移回归员工"

            duplicate = await client.post(
                f"/api/v1/organizations/{organization_id}/users",
                json=payload,
            )
            assert duplicate.status_code == 409, duplicate.text
            assert duplicate.json()["detail"] == "用户名“migration-user”已存在，请换一个用户名"

            deleted = await client.delete(f"/api/v1/users/{first_user_id}")
            assert deleted.status_code == 204, deleted.text

            recreated = await client.post(
                f"/api/v1/organizations/{organization_id}/users",
                json=payload,
            )
            assert recreated.status_code == 201, recreated.text
            second_user_id = UUID(recreated.json()["id"])
            assert second_user_id != first_user_id
    finally:
        app.dependency_overrides.clear()

    async with session_factory() as session:
        duplicate_row = User(
            organization_id=organization_id,
            username="migration-user",
            password_hash="test-only",
        )
        session.add(duplicate_row)
        with pytest.raises(IntegrityError) as captured:
            await session.flush()
        failure = classify_integrity_error(captured.value)
        assert failure.sqlstate == "23505"
        assert failure.constraint_name == "uq_user_org_username"
        translated = _user_integrity_http_error(failure, username="migration-user")
        assert translated.status_code == 409
        await session.rollback()

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(User)
                .where(User.organization_id == organization_id)
            )
        ).scalars().all()
        assert len(rows) == 2
        deleted_rows = [row for row in rows if row.deleted_at is not None]
        active_rows = [row for row in rows if row.deleted_at is None]
        assert len(deleted_rows) == 1
        assert deleted_rows[0].username.startswith("migration-user~deleted~")
        assert len(active_rows) == 1
        assert active_rows[0].username == "migration-user"
        assert active_rows[0].role == "member"

    connection = await asyncpg.connect(
        **_asyncpg_connect_kwargs(raw_url, database=raw_url.database or ""),
        timeout=5,
    )
    try:
        stored_roles = await connection.fetch(
            "SELECT id, role FROM users WHERE organization_id = $1",
            organization_id,
        )
        assert len(stored_roles) == 2
        assert {row["role"] for row in stored_roles} == {"member"}
    finally:
        await connection.close()
        await engine.dispose()
