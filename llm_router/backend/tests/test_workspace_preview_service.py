from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.services import workspace_preview_service as preview


@pytest.fixture(autouse=True)
def db_engine():
    """Pure preview tests do not need the PostgreSQL autouse fixture."""
    yield


def _file(raw: bytes, filename: str, mime: str, content_hash: str = "a" * 64):
    return SimpleNamespace(
        content=base64.b64encode(raw).decode("ascii"),
        content_hash=content_hash,
        path=filename,
        metadata_={"binary": True, "name": filename, "mime": mime},
    )


def test_pdf_original_preview_returns_unchanged_bytes():
    raw = b"%PDF-1.4\npreview"
    content, media_type, filename = preview.build_original_preview(
        _file(raw, "report.pdf", "application/pdf"), raw,
    )
    assert content == raw
    assert media_type == "application/pdf"
    assert filename == "report.pdf"


def test_office_preview_returns_original_bytes_and_media_type():
    source = _file(b"xlsx-bytes", "财务表.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    content, media_type, filename = preview.build_original_preview(source, b"xlsx-bytes")
    assert content == b"xlsx-bytes"
    assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert filename == "财务表.xlsx"


def test_office_preview_recovers_media_type_from_legacy_generic_mime():
    source = _file(b"xlsx-bytes", "财务表.xlsx", "application/octet-stream")
    content, media_type, filename = preview.build_original_preview(source, b"xlsx-bytes")
    assert content == b"xlsx-bytes"
    assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert filename == "财务表.xlsx"


def test_unknown_binary_preview_is_not_converted():
    content, media_type, filename = preview.build_original_preview(
        _file(b"data", "archive.zip", "application/zip"), b"data",
    )
    assert content == b"data"
    assert media_type == "application/zip"
    assert filename == "archive.zip"
