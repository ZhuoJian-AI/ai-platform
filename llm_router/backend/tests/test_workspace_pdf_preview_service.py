"""Faithful PDF page preview coverage."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.workspace_pdf_preview_service import _document_info, _original_jpeg, _render_page


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
