from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import workspace_preview_session_service as preview


@pytest.fixture(autouse=True)
def db_engine():
    """Routing-only tests do not need the PostgreSQL autouse fixture."""
    yield


def _file(name: str, size: int, *, object_storage: bool = True):
    return SimpleNamespace(
        id="file-1",
        path=name,
        size=size,
        content_ref="oss://projects/7/assets/file" if object_storage else "legacy/file",
        metadata_={
            "name": name,
            "mime": "application/pdf" if name.endswith(".pdf") else "application/octet-stream",
            "binary": True,
        },
        current_version_id="version-1",
    )


@pytest.mark.asyncio
async def test_small_pdf_uses_signed_pdfjs_range_source(monkeypatch):
    monkeypatch.setattr(settings, "workspace_weboffice_enabled", True)

    async def signed(_ref, *, filename, version_id):
        assert filename == "manual.pdf"
        assert version_id is None
        return {"url": "https://oss.example/manual.pdf", "fallback_url": None, "headers": {}}

    monkeypatch.setattr(preview.storage_gateway_service, "get_browser_signed_download", signed)
    result = await preview.create_preview_session(
        object(),
        _file("manual.pdf", 10 * 1024 * 1024),
        weboffice_user_id="user123",
        client_open_id="open12345",
    )

    assert result["mode"] == "pdfjs"
    assert result["url"].startswith("https://oss.example/")


@pytest.mark.asyncio
async def test_large_pdf_uses_signed_pdfjs_range_source_without_weboffice(monkeypatch):
    monkeypatch.setattr(settings, "workspace_weboffice_enabled", True)
    token_calls: list[str] = []

    async def token(*_args, **_kwargs):
        token_calls.append("called")
        return {"weboffice_url": "https://office.example/view", "access_token": "access", "refresh_token": "refresh"}

    async def signed(*_args, **_kwargs):
        return {"url": "https://oss.example/large.pdf", "fallback_url": None, "headers": {}}

    monkeypatch.setattr(preview.storage_gateway_service, "generate_weboffice_token", token)
    monkeypatch.setattr(preview.storage_gateway_service, "get_browser_signed_download", signed)
    result = await preview.create_preview_session(
        object(),
        _file("large.pdf", 80 * 1024 * 1024),
        weboffice_user_id="user123",
        client_open_id="open12345",
    )

    assert result["mode"] == "pdfjs"
    assert result["url"] == "https://oss.example/large.pdf"
    assert token_calls == []


@pytest.mark.asyncio
async def test_office_without_weboffice_enqueues_durable_fallback(monkeypatch):
    monkeypatch.setattr(settings, "workspace_weboffice_enabled", False)
    queued: list[str] = []

    async def enqueue(_db, file):
        queued.append(file.id)

    monkeypatch.setattr(preview, "enqueue_fallback", enqueue)
    result = await preview.create_preview_session(
        object(),
        _file("deck.pptx", 90 * 1024 * 1024),
        weboffice_user_id="user123",
        client_open_id="open12345",
    )

    assert result["mode"] == "fallback"
    assert queued == ["file-1"]


@pytest.mark.asyncio
async def test_over_200_mib_is_download_only(monkeypatch):
    monkeypatch.setattr(settings, "workspace_weboffice_enabled", True)
    result = await preview.create_preview_session(
        object(),
        _file("deck.pptx", 201 * 1024 * 1024),
        weboffice_user_id="user123",
        client_open_id="open12345",
    )

    assert result["mode"] == "download_only"
    assert "200MB" in result["reason"]


@pytest.mark.asyncio
async def test_legacy_office_file_does_not_enqueue_an_impossible_conversion(monkeypatch):
    monkeypatch.setattr(settings, "workspace_weboffice_enabled", True)
    queued: list[str] = []

    async def enqueue(_db, file):
        queued.append(file.id)

    monkeypatch.setattr(preview, "enqueue_fallback", enqueue)
    result = await preview.create_preview_session(
        object(),
        _file("legacy-deck.pptx", 10 * 1024 * 1024, object_storage=False),
        weboffice_user_id="user123",
        client_open_id="open12345",
    )

    assert result["mode"] == "download_only"
    assert "对象存储" in result["reason"]
    assert queued == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["small.docx", "small.xlsx"])
async def test_small_word_and_excel_use_free_browser_viewer(monkeypatch, name):
    token_calls: list[str] = []

    async def token(*_args, **_kwargs):
        token_calls.append("called")

    async def signed(*_args, **_kwargs):
        return {"url": "https://oss.example/file", "fallback_url": None, "headers": {}}

    monkeypatch.setattr(preview.storage_gateway_service, "generate_weboffice_token", token)
    monkeypatch.setattr(preview.storage_gateway_service, "get_browser_signed_download", signed)
    result = await preview.create_preview_session(
        object(),
        _file(name, 500 * 1024),
        weboffice_user_id="user123",
        client_open_id="open12345",
    )

    assert result["mode"] == "browser_office"
    assert token_calls == []


@pytest.mark.asyncio
async def test_text_never_calls_weboffice(monkeypatch):
    async def signed(*_args, **_kwargs):
        return {"url": "https://oss.example/file", "fallback_url": None, "headers": {}}

    monkeypatch.setattr(preview.storage_gateway_service, "get_browser_signed_download", signed)
    result = await preview.create_preview_session(
        object(),
        _file("notes.txt", 2 * 1024),
        weboffice_user_id="user123",
        client_open_id="open12345",
    )
    assert result["mode"] == "text"


@pytest.mark.asyncio
async def test_same_presentation_open_is_idempotent(monkeypatch):
    preview._session_cache.clear()
    monkeypatch.setattr(settings, "workspace_weboffice_enabled", True)
    token_calls: list[str] = []

    async def token(*_args, **_kwargs):
        token_calls.append("called")
        return {"weboffice_url": "https://office.example/view", "access_token": "access", "refresh_token": "refresh"}

    monkeypatch.setattr(preview.storage_gateway_service, "generate_weboffice_token", token)
    file = _file("deck.pptx", 30 * 1024 * 1024)
    first = await preview.create_preview_session(
        object(),
        file,
        weboffice_user_id="user123",
        client_open_id="same-open-id",
    )
    second = await preview.create_preview_session(
        object(),
        file,
        weboffice_user_id="user123",
        client_open_id="same-open-id",
    )
    assert first == second
    assert token_calls == ["called"]


@pytest.mark.asyncio
async def test_same_refresh_is_idempotent(monkeypatch):
    preview._session_cache.clear()
    monkeypatch.setattr(settings, "workspace_weboffice_enabled", True)
    calls: list[str] = []

    async def refresh(*_args, **_kwargs):
        calls.append("called")
        return {"access_token": "next-access", "refresh_token": "next-refresh"}

    monkeypatch.setattr(preview.storage_gateway_service, "refresh_weboffice_token", refresh)
    file = _file("deck.pptx", 30 * 1024 * 1024)
    values = []
    for _ in range(2):
        values.append(
            await preview.refresh_preview_session(
                file,
                access_token="old-access",
                refresh_token="old-refresh",
                refresh_context="context-value",
                weboffice_user_id="user123",
            )
        )
    assert values[0] == values[1]
    assert calls == ["called"]
