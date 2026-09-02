from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import storage_gateway_service as storage
from app.services import workspace_service


@pytest.fixture(autouse=True)
def db_engine():
    """Pure service tests do not need the PostgreSQL autouse fixture."""
    yield


def _configure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "storage_gateway_url", "https://storage.example.test")
    monkeypatch.setattr(settings, "storage_project_token", "project-token")
    monkeypatch.setattr(settings, "storage_public_endpoint", "https://oss-cn-hongkong.aliyuncs.com")
    monkeypatch.setattr(settings, "storage_internal_endpoint", "https://oss-cn-hongkong-internal.aliyuncs.com")
    monkeypatch.setattr(settings, "storage_accelerate_endpoint", "https://oss-accelerate.aliyuncs.com")


def test_internal_endpoint_rewrite_preserves_bucket_and_query(monkeypatch):
    _configure(monkeypatch)
    rewritten = storage._internal_signed_url(
        "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/1/assets/a.xlsx?Expires=1&Signature=x"
    )
    assert rewritten == (
        "https://bucket.oss-cn-hongkong-internal.aliyuncs.com/"
        "projects/1/assets/a.xlsx?Expires=1&Signature=x"
    )


@pytest.mark.asyncio
async def test_upload_and_download_use_scoped_signed_urls(monkeypatch):
    _configure(monkeypatch)
    calls: list[tuple[str, str]] = []

    class FakeResponse:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            calls.append(("POST", url))
            assert kwargs["headers"]["Authorization"] == "Bearer project-token"
            if url.endswith("/v1/uploads/sign"):
                return FakeResponse({
                    "object_key": "projects/7/assets/report.xlsx",
                    "url": "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/7/assets/report.xlsx?sig=1",
                    "headers": {"Content-Type": "application/test"},
                })
            return FakeResponse({
                "object_key": kwargs["json"]["object_key"],
                "url": "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/7/assets/report.xlsx?sig=2",
            })

        async def put(self, url, **kwargs):
            calls.append(("PUT", url))
            assert "oss-cn-hongkong-internal" in url
            assert kwargs["content"] == b"original"
            return FakeResponse()

        async def get(self, url):
            calls.append(("GET", url))
            assert "oss-cn-hongkong-internal" in url
            return FakeResponse(content=b"original")

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    ref = await storage.upload_bytes(b"original", filename="report.xlsx", content_type="application/test")
    assert ref == "oss://projects/7/assets/report.xlsx"
    assert await storage.download_bytes(ref) == b"original"
    assert [method for method, _ in calls] == ["POST", "PUT", "POST", "GET"]


@pytest.mark.asyncio
async def test_browser_signed_download_uses_acceleration_with_public_fallback(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "url": "https://bucket.oss-cn-hongkong.aliyuncs.com/projects/7/assets/deck.pptx?sig=browser",
                "headers": {},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            assert url.endswith("/v1/downloads/sign")
            assert kwargs["json"] == {
                "object_key": "projects/7/assets/deck.pptx",
                "expires_in_seconds": 900,
            }
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    signed = await storage.get_browser_signed_download("oss://projects/7/assets/deck.pptx")
    assert signed["url"].startswith("https://bucket.oss-accelerate.aliyuncs.com/")
    assert "-internal" not in signed["url"]
    assert signed["fallback_url"].startswith("https://bucket.oss-cn-hongkong.aliyuncs.com/")


@pytest.mark.asyncio
async def test_browser_signed_download_rewrites_accelerated_gateway_url_to_public_fallback(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "url": "https://bucket.oss-accelerate.aliyuncs.com/projects/7/assets/deck.pptx?sig=browser",
                "headers": {},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    signed = await storage.get_browser_signed_download("oss://projects/7/assets/deck.pptx")
    assert signed["url"].startswith("https://bucket.oss-accelerate.aliyuncs.com/")
    assert signed["fallback_url"].startswith("https://bucket.oss-cn-hongkong.aliyuncs.com/")


@pytest.mark.asyncio
async def test_large_browser_upload_requests_parallel_multipart(monkeypatch):
    _configure(monkeypatch)
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "session_id": "multipart-1",
                "object_key": "projects/7/assets/deck.pptx",
                "part_size": 100 * 1024 * 1024,
                "expected_parts": 5,
                "expires_at": "2026-09-01T00:00:00Z",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured.update({"url": url, "headers": kwargs["headers"], "json": kwargs["json"]})
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    result = await storage.sign_browser_upload(
        filename="deck.pptx",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        size_bytes=500 * 1024 * 1024,
    )

    assert captured["url"].endswith("/v1/multipart/initiate")
    assert captured["headers"]["X-Storage-Subject"] == "ai-platform-control-plane"
    assert captured["json"]["force_multipart"] is True
    assert captured["json"]["part_size_bytes"] == 8 * 1024 * 1024
    assert result["method"] == "MULTIPART"
    assert result["expected_parts"] == 5


@pytest.mark.asyncio
async def test_large_browser_upload_uses_small_parts_in_weak_network_mode(monkeypatch):
    _configure(monkeypatch)
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "session_id": "multipart-weak",
                "object_key": "projects/7/assets/deck.pptx",
                "part_size": 1024 * 1024,
                "expected_parts": 101,
                "expires_at": "2026-09-01T00:00:00Z",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    result = await storage.sign_browser_upload(
        filename="deck.pptx",
        content_type="application/octet-stream",
        size_bytes=101 * 1024 * 1024,
        weak_network=True,
    )
    assert captured["part_size_bytes"] == 2 * 1024 * 1024
    assert result["part_size"] == 1024 * 1024


@pytest.mark.asyncio
async def test_stream_signed_download_proxies_internal_object_in_chunks(monkeypatch):
    _configure(monkeypatch)

    class FakeStreamResponse:
        headers = {"content-length": "8"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, _chunk_size):
            yield b"original"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, method, url, **kwargs):
            assert method == "GET"
            assert "oss-cn-hongkong-internal" in url
            assert kwargs["headers"] == {"x-test": "download"}
            return FakeStreamResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    chunks = [chunk async for chunk in storage.stream_signed_download(
        "https://bucket.oss-cn-hongkong-internal.aliyuncs.com/report.xlsx?sig=2",
        headers={"x-test": "download"},
        max_bytes=100,
    )]
    assert chunks == [b"original"]


@pytest.mark.asyncio
async def test_workspace_loads_external_bytes_and_verifies_hash(monkeypatch):
    raw = b"external file"
    file = SimpleNamespace(
        content_ref="oss://projects/7/assets/file.pdf",
        content=None,
        content_hash=hashlib.sha256(raw).hexdigest(),
        metadata_={"binary": True},
    )

    async def fake_download(_ref: str) -> bytes:
        return raw

    monkeypatch.setattr(storage, "download_bytes", fake_download)
    assert await workspace_service.load_file_bytes(file) == raw


@pytest.mark.asyncio
async def test_workspace_rejects_external_hash_mismatch(monkeypatch):
    file = SimpleNamespace(
        content_ref="oss://projects/7/assets/file.pdf",
        content=None,
        content_hash="0" * 64,
        metadata_={"binary": True},
    )

    async def fake_download(_ref: str) -> bytes:
        return b"tampered"

    monkeypatch.setattr(storage, "download_bytes", fake_download)
    with pytest.raises(workspace_service.WorkspaceFileUploadError, match="完整性校验失败"):
        await workspace_service.load_file_bytes(file)


@pytest.mark.asyncio
async def test_object_listing_is_normalized_for_orphan_reconciliation(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [
                    {"object_key": "projects/1/kept.bin", "size_bytes": 12, "created_at": "2026-01-01"},
                    {"invalid": True},
                ],
                "next_cursor": "page-2",
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **kwargs):
            assert url.endswith("/v1/objects")
            assert kwargs["headers"]["Authorization"] == "Bearer project-token"
            assert kwargs["params"]["limit"] == 500
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    result = await storage.list_project_objects(older_than=datetime.now(UTC))
    assert result == {
        "items": [{"object_key": "projects/1/kept.bin", "size": 12, "created_at": "2026-01-01"}],
        "next_cursor": "page-2",
    }


@pytest.mark.asyncio
async def test_object_listing_safely_skips_legacy_gateway(monkeypatch):
    _configure(monkeypatch)

    class FakeResponse:
        status_code = 404

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(storage.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    assert await storage.list_project_objects(older_than=datetime.now(UTC)) is None
