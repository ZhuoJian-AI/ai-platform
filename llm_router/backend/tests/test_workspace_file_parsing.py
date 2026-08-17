"""工作空间文件向 LLM 暴露解析文本，不暴露 Base64。"""

from types import SimpleNamespace

import pytest

from app.services.workspace_service import paginate_file_content, resolve_file_content


@pytest.fixture(autouse=True)
def db_engine():
    """纯函数单测不启动 conftest 的 PostgreSQL autouse fixture。"""
    yield


def test_text_file_returns_original_content() -> None:
    file = SimpleNamespace(metadata_={}, content="hello", path="notes.md")

    assert resolve_file_content(file) == "hello"


def test_ready_binary_returns_extracted_text_not_base64() -> None:
    file = SimpleNamespace(
        metadata_={"binary": True},
        content="UEsDBBase64ShouldNeverLeak",
        extracted_text="结构化解析结果",
        parse_status="ready",
        parse_error=None,
        path="报告.docx",
    )

    result = resolve_file_content(file)

    assert result == "结构化解析结果"
    assert "UEsDB" not in result


def test_binary_context_is_capped_with_notice() -> None:
    file = SimpleNamespace(
        metadata_={"binary": True},
        content="binary",
        extracted_text="中" * 12,
        parse_status="ready",
        parse_error=None,
        path="超长.pdf",
    )

    result = resolve_file_content(file, max_chars=10)

    assert result.startswith("中" * 10)
    assert "原文 12 字符" in result
    assert "最多注入 10 字符" in result


def test_failed_binary_returns_reason_not_base64() -> None:
    file = SimpleNamespace(
        metadata_={"binary": True},
        content="UEsDBBase64ShouldNeverLeak",
        extracted_text=None,
        parse_status="failed",
        parse_error="文件已加密",
        path="机密.xlsx",
    )

    result = resolve_file_content(file)

    assert "文件已加密" in result
    assert "UEsDB" not in result


def test_paginated_content_reports_continuation() -> None:
    file = SimpleNamespace(
        id="file-1",
        metadata_={"name": "报告.txt"},
        content="第一行\n第二行\n第三行",
        path="报告.txt",
    )

    first = paginate_file_content(file, offset=1, limit=2)
    second = paginate_file_content(file, offset=first["next_offset"], limit=2)

    assert first == {
        "file_id": "file-1",
        "path": "报告.txt",
        "original_filename": "报告.txt",
        "status": "ready",
        "offset": 1,
        "end_line": 2,
        "total_lines": 3,
        "has_more": True,
        "next_offset": 3,
        "truncated_reason": None,
        "content": "第一行\n第二行",
    }
    assert second["content"] == "第三行"
    assert second["has_more"] is False
    assert second["next_offset"] is None


def test_paginated_content_validates_bounds_and_byte_cap() -> None:
    file = SimpleNamespace(
        id="file-2", metadata_={}, content="中" * 100, path="single-line.txt",
    )

    capped = paginate_file_content(file, max_bytes=20)
    out_of_range = paginate_file_content(file, offset=2)

    assert len(capped["content"].encode("utf-8")) <= 20
    assert capped["truncated_reason"] == "line_exceeds_byte_limit"
    assert capped["has_more"] is False
    assert out_of_range["status"] == "error"
    assert "out of range" in out_of_range["error"]


def test_paginated_binary_failure_never_returns_base64() -> None:
    file = SimpleNamespace(
        id="file-3",
        metadata_={"binary": True, "name": "加密.xlsx"},
        content="UEsDBBase64ShouldNeverLeak",
        extracted_text=None,
        parse_status="failed",
        parse_error="文件已加密",
        path="加密.xlsx",
    )

    result = paginate_file_content(file)

    assert result["status"] == "unavailable"
    assert result["error"] == "文件已加密"
    assert "UEsDB" not in str(result)
