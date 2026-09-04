"""Regression tests for stable workspace-file identities and versions.

Only a live path is unique.  Deleting then uploading the same path creates a
new identity so an old task reference can never silently resolve to new data.

自包含：本测试自建引擎；文件版本与审计字段引入跨表外键后，使用完整元数据
建表，使软删除唯一约束回归场景与全局 API 测试夹具相互隔离。
"""

import hashlib
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.base import Base
from app.models.organization import Organization
from app.models.workspace import (
    Workspace,
    WorkspaceFile,
    WorkspaceFileEventOutbox,
    WorkspaceFileVersion,
)
from app.schemas.workspace import WorkspaceFileCreate, WorkspaceFileUpdate
from app.services import workspace_service

_TEST_DB = "ai_infra_ws_upsert_test"


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
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, checkfirst=True)
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.drop_all(c, checkfirst=True)
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
async def test_upsert_after_delete_creates_new_file_identity(session: AsyncSession):
    """同路径重传保留旧删除身份，且创建新文件 UUID。"""
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

    f2 = await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
        path="报告.docx", content="BBBB", metadata={"task_id": "new-task"}))
    await db.flush()

    assert f2.id != f1.id
    assert f1.deleted_at is not None
    assert f2.deleted_at is None
    assert f2.content == "BBBB"
    assert f2.metadata_.get("task_id") == "new-task"

    rows = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == ws.id, WorkspaceFile.path == "报告.docx"
    ))).scalars().all()
    assert len(rows) == 2
    assert sum(row.deleted_at is None for row in rows) == 1


@pytest.mark.asyncio
async def test_create_rejects_live_same_path_without_version_precondition(session: AsyncSession):
    """Create/upload must never silently overwrite a stable logical file."""
    db = session
    ws = await _make_workspace(db)
    await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
        path="notes.md", content="v1"))
    await db.flush()
    with pytest.raises(workspace_service.WorkspaceFilePathConflict) as caught:
        await workspace_service.upsert_file(db, ws, WorkspaceFileCreate(
            path="notes.md", content="v2"))
    assert caught.value.current_version_id
    rows = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == ws.id, WorkspaceFile.path == "notes.md"
    ))).scalars().all()
    assert len(rows) == 1
    assert rows[0].content == "v1"


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


@pytest.mark.asyncio
async def test_editing_oss_csv_switches_to_verified_new_object(
    session: AsyncSession, monkeypatch,
):
    """A text PATCH must not leave preview/download bound to the old OSS key."""
    db = session
    ws = await _make_workspace(db)
    original = "姓名,数量\n旧值,1\n"
    edited = "姓名,数量\n新值,2\n"
    refs = {
        original.encode(): "oss://projects/7/assets/original.csv",
        edited.encode(): "oss://projects/7/assets/edited.csv",
    }

    async def fake_upload(payload: bytes, *, filename: str, content_type: str) -> str:
        assert filename == "明细.csv"
        assert content_type == "text/csv"
        return refs[payload]

    async def fake_inspect(content_ref: str, *, version_id=None) -> dict:
        assert content_ref == refs[edited.encode()]
        assert version_id is None
        return {
            "size": len(edited.encode()),
            "etag": "edited-etag",
            "version_id": "oss-version-2",
            "content_type": "text/csv",
            "content_hash": hashlib.sha256(edited.encode()).hexdigest(),
        }

    async def fake_download(content_ref: str, *, version_id=None) -> bytes:
        assert content_ref == refs[edited.encode()]
        assert version_id == "oss-version-2"
        return edited.encode()

    monkeypatch.setattr(settings, "workspace_object_storage_enabled", True)
    monkeypatch.setattr(settings, "storage_gateway_url", "https://storage.example.test")
    monkeypatch.setattr(settings, "storage_project_token", "test-token")
    monkeypatch.setattr(workspace_service.storage_gateway_service, "upload_bytes", fake_upload)
    monkeypatch.setattr(workspace_service.storage_gateway_service, "inspect_object", fake_inspect)
    monkeypatch.setattr(workspace_service.storage_gateway_service, "download_bytes", fake_download)

    file = await workspace_service.ingest_uploaded_file(
        db, ws, path="明细.csv", filename="明细.csv", content_type="text/csv",
        raw=original.encode(),
    )
    old_ref = file.content_ref
    old_version = file.current_version_id
    updated = await workspace_service.update_file(
        db,
        file,
        WorkspaceFileUpdate(
            content=edited,
            base_version_id=old_version,
            idempotency_key="csv-browser-save-0001",
        ),
    )

    assert updated.content_ref != old_ref
    assert updated.content_ref == refs[edited.encode()]
    assert updated.content is None
    assert updated.extracted_text == edited
    assert updated.content_hash == hashlib.sha256(edited.encode()).hexdigest()
    assert updated.metadata_["storage_version_id"] == "oss-version-2"
    assert updated.metadata_["etag"] == "edited-etag"
    assert await workspace_service.load_file_bytes(updated) == edited.encode()
    events = list((await db.execute(select(WorkspaceFileEventOutbox).where(
        WorkspaceFileEventOutbox.workspace_file_id == updated.id,
    ))).scalars().all())
    assert [event.event_type for event in events] == ["version_created", "version_created"]


@pytest.mark.asyncio
async def test_update_by_id_preserves_identity_and_is_idempotent(session: AsyncSession):
    ws = await _make_workspace(session)
    file = await workspace_service.upsert_file(
        session, ws, WorkspaceFileCreate(path="shared/report.txt", content="v1"),
    )
    original_id = file.id
    base_version_id = file.current_version_id

    updated = await workspace_service.update_file(
        session,
        file,
        WorkspaceFileUpdate(
            content="v2",
            base_version_id=base_version_id,
            idempotency_key="update-report-0001",
        ),
    )
    new_version_id = updated.current_version_id
    assert updated.id == original_id
    assert new_version_id != base_version_id
    assert updated.content == "v2"

    replayed = await workspace_service.update_file(
        session,
        updated,
        WorkspaceFileUpdate(
            content="v2",
            base_version_id=base_version_id,
            idempotency_key="update-report-0001",
        ),
    )
    assert replayed.id == original_id
    assert replayed.current_version_id == new_version_id
    await workspace_service.update_file(
        session,
        replayed,
        WorkspaceFileUpdate(
            content="v3",
            base_version_id=new_version_id,
            idempotency_key="update-report-0002",
        ),
    )
    latest_version_id = replayed.current_version_id
    old_replay = await workspace_service.update_file(
        session,
        replayed,
        WorkspaceFileUpdate(
            content="v2",
            base_version_id=base_version_id,
            idempotency_key="update-report-0001",
        ),
    )
    assert old_replay.current_version_id == latest_version_id
    assert old_replay.mutation_result_version_id == new_version_id
    versions = list((await session.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == original_id,
    ))).scalars().all())
    assert len(versions) == 3


@pytest.mark.asyncio
async def test_update_rejects_stale_base_with_current_version(session: AsyncSession):
    ws = await _make_workspace(session)
    file = await workspace_service.upsert_file(
        session, ws, WorkspaceFileCreate(path="shared/stale.txt", content="v1"),
    )
    stale_version_id = file.current_version_id
    await workspace_service.update_file(
        session,
        file,
        WorkspaceFileUpdate(
            content="v2",
            base_version_id=stale_version_id,
            idempotency_key="update-stale-0001",
        ),
    )
    current_version_id = file.current_version_id

    with pytest.raises(workspace_service.WorkspaceFileVersionConflict) as exc_info:
        await workspace_service.update_file(
            session,
            file,
            WorkspaceFileUpdate(
                content="v3",
                base_version_id=stale_version_id,
                idempotency_key="update-stale-0002",
            ),
        )
    assert exc_info.value.current_version_id == str(current_version_id)


@pytest.mark.asyncio
async def test_plain_text_update_rejects_office_binary_without_changing_version(
    session: AsyncSession,
):
    ws = await _make_workspace(session)
    file = await workspace_service.upsert_file(
        session,
        ws,
        WorkspaceFileCreate(
            path="共享/原表.xlsx",
            content="UEsDBA==",
            metadata={
                "binary": True,
                "name": "原表.xlsx",
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ),
    )
    original_version = file.current_version_id
    original_content = file.content
    with pytest.raises(workspace_service.WorkspaceFileUnsupportedTextUpdate):
        await workspace_service.update_file(
            session,
            file,
            WorkspaceFileUpdate(
                content="这不是一个合法的 XLSX 文件",
                base_version_id=original_version,
                idempotency_key="reject-office-text-0001",
            ),
        )
    assert file.current_version_id == original_version
    assert file.content == original_content
    versions = list((await session.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == file.id,
    ))).scalars().all())
    assert len(versions) == 1


@pytest.mark.asyncio
async def test_cross_workspace_move_preserves_file_id_and_version_history(
    session: AsyncSession,
):
    source_ws = await _make_workspace(session)
    target_ws = Workspace(
        organization_id=source_ws.organization_id,
        name="生产部",
        slug="production",
        scope_type="department",
    )
    session.add(target_ws)
    await session.flush()
    file = await workspace_service.upsert_file(
        session, source_ws, WorkspaceFileCreate(path="尺寸表/AD2604.xlsx", content="v1"),
    )
    stable_file_id = file.id
    source_version = file.current_version_id
    moved = await workspace_service.move_file(
        session,
        file,
        "2026冬/AD2604.xlsx",
        target_workspace=target_ws,
        base_version_id=source_version,
        idempotency_key="cross-workspace-move-0001",
    )
    move_version = moved.current_version_id
    assert moved.id == stable_file_id
    assert moved.workspace_id == target_ws.id
    assert moved.path == "2026冬/AD2604.xlsx"
    assert move_version != source_version

    await workspace_service.update_file(
        session,
        moved,
        WorkspaceFileUpdate(
            content="v2",
            base_version_id=move_version,
            idempotency_key="post-move-update-0001",
        ),
    )
    latest_version = moved.current_version_id
    replay = await workspace_service.move_file(
        session,
        moved,
        "2026冬/AD2604.xlsx",
        target_workspace=target_ws,
        base_version_id=source_version,
        idempotency_key="cross-workspace-move-0001",
    )
    assert replay.current_version_id == latest_version
    assert replay.mutation_result_version_id == move_version
    versions = list((await session.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == stable_file_id,
    ).order_by(WorkspaceFileVersion.version_no))).scalars().all())
    assert len(versions) == 3


@pytest.mark.asyncio
async def test_copy_idempotency_replay_returns_original_workspace_path_and_version(
    session: AsyncSession,
):
    source_ws = await _make_workspace(session)
    target_ws = Workspace(
        organization_id=source_ws.organization_id,
        name="生产部", slug="copy-target", scope_type="department",
    )
    later_ws = Workspace(
        organization_id=source_ws.organization_id,
        name="技术部", slug="copy-later", scope_type="department",
    )
    session.add_all([target_ws, later_ws])
    await session.flush()
    source = await workspace_service.upsert_file(
        session, source_ws, WorkspaceFileCreate(path="source.txt", content="source"),
    )
    actor_id = uuid4()
    copied = await workspace_service.copy_file(
        session, source, target_ws, "交付/result.txt",
        base_version_id=source.current_version_id,
        idempotency_key="copy-original-result-0001",
        actor_type="user", actor_id=actor_id,
    )
    copied_id = copied.id
    copied_version_id = copied.current_version_id
    await workspace_service.move_file(
        session, copied, "归档/moved.txt", target_workspace=later_ws,
        base_version_id=copied.current_version_id,
        idempotency_key="move-copied-result-0001",
    )

    replay = await workspace_service.copy_file(
        session, source, target_ws, "交付/result.txt",
        base_version_id=source.current_version_id,
        idempotency_key="copy-original-result-0001",
        actor_type="user", actor_id=actor_id,
    )
    assert replay.id == copied_id
    assert replay.workspace_id == target_ws.id
    assert replay.path == "交付/result.txt"
    assert replay.current_version_id == copied_version_id
    assert replay.mutation_result_version_id == copied_version_id
    live = await workspace_service.get_file(session, copied_id)
    assert live is not None
    assert live.workspace_id == later_ws.id
    assert live.path == "归档/moved.txt"


@pytest.mark.asyncio
async def test_cross_workspace_search_is_paginated_in_sql(session: AsyncSession):
    first_ws = await _make_workspace(session)
    second_ws = Workspace(
        organization_id=first_ws.organization_id,
        name="部门空间",
        slug="ws-2",
        scope_type="department",
    )
    session.add(second_ws)
    await session.flush()
    first = await workspace_service.upsert_file(
        session, first_ws, WorkspaceFileCreate(path="reports/a.txt", content="a"),
    )
    second = await workspace_service.upsert_file(
        session, second_ws, WorkspaceFileCreate(path="reports/b.txt", content="b"),
    )

    first_page, has_more = await workspace_service.search_files(
        session, [first_ws.id, second_ws.id], query="reports", offset=0, limit=1,
    )
    second_page, final_has_more = await workspace_service.search_files(
        session, [first_ws.id, second_ws.id], query="reports", offset=1, limit=1,
    )

    assert len(first_page) == 1
    assert has_more is True
    assert len(second_page) == 1
    assert final_has_more is False
    assert {first_page[0].id, second_page[0].id} == {first.id, second.id}
