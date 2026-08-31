"""Faithful PDF page preview coverage."""

from __future__ import annotations

import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import workspace_pdf_preview_service
from app.services.workspace_pdf_preview_service import (
    _document_info,
    _office_preview_ref,
    _original_jpeg,
    _render_page,
)


@pytest.fixture(autouse=True)
def db_engine():
    """These tests are pure and do not require PostgreSQL."""
    yield


def test_full_page_jpeg_is_returned_without_reencoding() -> None:
    payload = b"\xff\xd8original-jpeg\xff\xd9"
    page = SimpleNamespace(
        width=4001,
        height=2251,
        images=[{
            "x0": 0,
            "top": 0,
            "x1": 4001,
            "bottom": 2251,
            "stream": SimpleNamespace(rawdata=payload),
        }],
    )

    assert _original_jpeg(page) == payload


def test_partial_page_jpeg_uses_raster_fallback() -> None:
    page = SimpleNamespace(
        width=100,
        height=100,
        images=[{
            "x0": 10,
            "top": 10,
            "x1": 90,
            "bottom": 90,
            "stream": SimpleNamespace(rawdata=b"\xff\xd8partial\xff\xd9"),
        }],
    )

    assert _original_jpeg(page) is None


def test_generated_image_pdf_returns_real_original_page(tmp_path) -> None:
    path = tmp_path / "image-page.pdf"
    source = Image.new("RGB", (320, 180), (32, 96, 160))
    source.save(path, "PDF", resolution=96)

    info = _document_info(path)
    content, media_type = _render_page(path, 1)
    rendered = Image.open(io.BytesIO(content))

    assert info["page_count"] == 1
    assert media_type in {"image/jpeg", "image/png"}
    assert rendered.width > 0
    assert rendered.height > 0
    assert rendered.convert("RGB").getpixel((rendered.width // 2, rendered.height // 2)) != (255, 255, 255)


@pytest.mark.asyncio
async def test_office_preview_is_converted_once_and_persisted(monkeypatch) -> None:
    file = SimpleNamespace(
        id="file-1",
        path="brief.pptx",
        size=1024,
        content_ref="oss://source.pptx",
        content_hash="abc",
        current_version_id="version-1",
        metadata_={"name": "brief.pptx"},
    )

    class FakeDb:
        commits = 0

        async def refresh(self, _file):
            return None

        async def commit(self):
            self.commits += 1

    db = FakeDb()
    conversions = 0

    async def fake_signed(_content_ref):
        return {"url": "https://internal.example/source", "headers": {}}

    async def fake_execute(**_kwargs):
        nonlocal conversions
        conversions += 1
        raw = b"%PDF-1.7\npreview"
        return {"outputs": [{"content_base64": base64.b64encode(raw).decode("ascii")}]}, 5

    async def fake_upload(_raw, **_kwargs):
        return "oss://preview.pdf"

    monkeypatch.setattr(workspace_pdf_preview_service.storage_gateway_service, "get_signed_download", fake_signed)
    monkeypatch.setattr(workspace_pdf_preview_service.skill_runner_client, "execute_builtin", fake_execute)
    monkeypatch.setattr(workspace_pdf_preview_service.storage_gateway_service, "upload_bytes", fake_upload)

    assert await _office_preview_ref(db, file) == "oss://preview.pdf"
    assert await _office_preview_ref(db, file) == "oss://preview.pdf"
    assert conversions == 1
    assert db.commits == 1
