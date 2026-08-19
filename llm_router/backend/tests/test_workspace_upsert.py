"""Regression tests for ``workspace_service.upsert_file`` soft-delete collision.

背景：``uq_wsfile_path`` 唯一约束是 ``(workspace_id, path)`` 且**不含** deleted_at。
旧实现按 ``deleted_at IS NULL`` 过滤查存量行，软删记录被漏掉 → 走 INSERT → 命中
唯一约束冲突（UniqueViolationError）。该异常在 ``_execute_builtin_tool`` 里被捕获
但未回滚主事务，致 run 主事务进入 PendingRollback 态，最终 save_memory 的 flush
失败、本轮 assistant 消息被回滚而「消失」（sal-channel / hr-recruiter 复现路径）。

修复后：同路径即便存在软删记录，upsert 应复活该行并覆盖内容，不再 INSERT 冲突。

自包含：本测试自建引擎 + 仅创建所需 3 张表（organizations / workspaces /
workspace_files），使软删除唯一约束回归场景与全局 API 测试夹具相互隔离。
"""

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.base import Base
from app.models.organization import Organization
from app.models.workspace import Workspace, WorkspaceFile
from app.schemas.workspace import WorkspaceFileCreate
from app.services import workspace_service

_TEST_DB = "ai_infra_ws_upsert_test"
_TABLES = [Organization.__table__, Workspace.__table__, WorkspaceFile.__table__]


# 本测试自建引擎 + 仅建 3 张表，不复用 conftest 的全量 ``db_engine`` autouse fixture，
# 让该回归场景使用独立数据库生命周期。在此于本模块内覆盖为 no-op。
@pytest_asyncio.fixture(autouse=True)
async def db_engine():  # noqa: D401 — overrides conftest autouse fixture for this module
    yield


@pytest.fixture(scope="module")
def _test_db_url() -> str:
    maint = make_url(str(settings.database_url))
    # 同步确保测试库存在（一次性事件循环，避免跨循环复用 asyncpg 连接）
    import asyncio

    async def _ensure():
        conn = await asyncpg.connect(
            host=maint.host, port=maint.port or 5432,
            user=maint.username, password=maint.password, database=maint.database,
        )
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB)
            if not exists:
                await conn.execute(f'CREATE DATABASE "{_TEST_DB}"')
        finally:
            await conn.close()

    asyncio.run(_ensure())
    return f"postgresql+asyncpg://{maint.username}:{maint.password}@{maint.host}:{maint.port or 5432}/{_TEST_DB}"


@pytest_asyncio.fixture
async def session(_test_db_url: str) -> AsyncSession:
    engine = create_async_engine(_test_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=_TABLES, checkfirst=True)
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.drop_all(c, tables=_TABLES, checkfirst=True)
        )
    await engine.dispose()


async def _make_workspace(db) -> Workspace:
    org = Organization(name="测试组织", slug="t-org")
    db.add(org)
    await db.flush()
    ws = Workspace(organization_id=org.id, name="个人空间", slug="ws",
                   scope_type="user", scope_id=None)
    db.add(ws)
    await db.flush()
    return ws


@pytest.mark.asyncio
async def test_upsert_revives_soft_deleted_same_path(session: AsyncSession):
    """同路径软删记录被复活并覆盖，不触发唯一约束冲突。"""
    db = session
    ws = await _make_workspace(db)

    f1 = await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
        path="报告.docx", content="AAAA", metadata={"binary": False}))
    await db.flush()
    assert f1.deleted_at is None
    assert f1.content == "AAAA"

    await workspace_service.soft_delete_file(db, f1)
    await db.flush()
    assert f1.deleted_at is not None

    # 旧实现此处 INSERT → UniqueViolation；修复后复活旧行、覆盖内容
    f2 = await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
        path="报告.docx", content="BBBB", metadata={"task_id": "new-task"}))
    await db.flush()

    assert f2.id == f1.id
    assert f2.deleted_at is None
    assert f2.content == "BBBB"
    assert f2.metadata_.get("task_id") == "new-task"

    rows = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == ws.id, WorkspaceFile.path == "报告.docx"
    ))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_upsert_overwrites_live_same_path(session: AsyncSession):
    """同路径存活记录走覆盖分支（行为不变，回归保护）。"""
    db = session
    ws = await _make_workspace(db)
    await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
        path="notes.md", content="v1"))
    await db.flush()
    f = await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
        path="notes.md", content="v2"))
    await db.flush()
    assert f.content == "v2"
    rows = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == ws.id, WorkspaceFile.path == "notes.md"
    ))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_binary_upload_uses_object_reference_when_enabled(
    session: AsyncSession, monkeypatch,
):
    db = session
    ws = await _make_workspace(db)
    raw = "工作空间 OSS 内容".encode()

    async def fake_upload(payload: bytes, *, filename: str, content_type: str) -> str:
        assert payload == raw
        assert filename == "说明.txt"
        assert content_type == "text/plain"
        return "oss://projects/7/assets/test.txt"

    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "storage_gateway_url", "https://storage.example.test")
    monkeypatch.setattr(settings, "storage_project_token", "test-token")
    monkeypatch.setattr(workspace_service.storage_gateway_service, "upload_bytes", fake_upload)

    file = await workspace_service.ingest_uploaded_file(
        db,
        ws,
        path="说明.txt",
        filename="说明.txt",
        content_type="text/plain",
        raw=raw,
    )

    assert file.content is None
    assert file.content_ref == "oss://projects/7/assets/test.txt"
    assert file.size == len(raw)
    assert file.metadata_["storage_backend"] == "oss_gateway"
    assert file.extracted_text == "工作空间 OSS 内容"
