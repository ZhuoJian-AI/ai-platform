from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
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


def test_office_preview_converts_once_and_reuses_hash_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "original_preview_cache_root", str(tmp_path))
    monkeypatch.setattr(preview.shutil, "which", lambda _: "/usr/bin/libreoffice")
    calls = 0

    def fake_run(command, **_kwargs):
        nonlocal calls
        calls += 1
        output = Path(command[command.index("--outdir") + 1])
        (output / "source.pdf").write_bytes(b"%PDF-converted")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(preview.subprocess, "run", fake_run)
    source = _file(b"xlsx-bytes", "财务表.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    first = preview.build_original_preview(source, b"xlsx-bytes")
    second = preview.build_original_preview(source, b"xlsx-bytes")
    assert first[0] == second[0] == b"%PDF-converted"
    assert first[1] == "application/pdf"
    assert calls == 1


def test_unsupported_original_preview_has_explicit_error():
    with pytest.raises(preview.OriginalPreviewError, match="暂不支持"):
        preview.build_original_preview(_file(b"data", "archive.zip", "application/zip"), b"data")
