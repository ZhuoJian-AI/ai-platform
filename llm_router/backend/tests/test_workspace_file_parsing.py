"""工作空间文件向 LLM 暴露解析文本，不暴露 Base64。"""

from types import SimpleNamespace

import pytest

from app.services.workspace_service import resolve_file_content


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
