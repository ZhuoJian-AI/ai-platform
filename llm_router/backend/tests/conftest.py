"""Test configuration and fixtures."""

import asyncio
import os

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.admin_auth import (
    CurrentAdmin,
    require_admin,
    require_admin_role,
    require_super_admin,
)
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.admin import Admin
from app.models.base import Base

# 测试用 PostgreSQL 数据库（与生产同构，确保 JSONB / FK / 类型语义一致）。
# 默认指向本地 Docker Postgres 上的 ai_infra_test 库；可用环境变量覆盖。
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ai_infra:ai_infra@localhost:5434/ai_infra_test",
)


async def _create_test_db_if_missing() -> None:
    """连到开发库执行 CREATE DATABASE（若测试库不存在）。

    在一次性事件循环中运行，与测试用例的事件循环隔离，避免 asyncpg
    连接跨循环复用导致的 "another operation is in progress"。
    """
    test_url = make_url(TEST_DATABASE_URL)
    test_db = test_url.database

    maint_url = make_url(str(settings.database_url))
    conn = await asyncpg.connect(
        host=maint_url.host,
        port=maint_url.port or 5432,
        user=maint_url.username,
        password=maint_url.password,
        database=maint_url.database,
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", test_db)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{test_db}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _ensure_test_db():
    """确保测试数据库存在（同步 fixture，使用一次性事件循环）。"""
    asyncio.run(_create_test_db_if_missing())
    yield


@pytest_asyncio.fixture(autouse=True)
async def db_engine(_ensure_test_db):
    """每个用例创建独立引擎并建表，结束后清表并释放引擎。

    每个用例独享一个绑定到该用例事件循环的引擎/连接池，
    避免 asyncpg 连接跨测试循环复用。
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        # 后续阶段引入 pgvector 的 RagChunk.embedding 列，测试库需先激活扩展。
        await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Yield a test database session bound to the per-test engine."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    """Yield an HTTP test client with DB session + admin auth overridden.

    管理类 API 需要 admin 鉴权；测试中以 super_admin 身份绕过 JWT 校验，
    同时复用注入的 db_session，保证读写落到测试库。
    """

    async def override_get_db():
        yield db_session

    test_admin = Admin(
        username="test-admin",
        password_hash="x",
        role="super_admin",
        is_active=True,
    )
    # Persist the overridden principal so audit/version foreign keys exercise
    # the same invariant as production authentication.
    db_session.add(test_admin)
    await db_session.flush()
    test_auth = CurrentAdmin(
        admin=test_admin,
        id=test_admin.id,
        username=test_admin.username,
        role="super_admin",
    )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: test_auth
    app.dependency_overrides[require_admin_role] = lambda: test_auth
    app.dependency_overrides[require_super_admin] = lambda: test_auth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
