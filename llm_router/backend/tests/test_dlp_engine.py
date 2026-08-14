"""Tests for DLP Engine."""

from uuid import uuid4

import pytest

from app.dlp.engine import DLPEngine
from app.models.dlp_rule import DlpRule


def _make_rule(
    rule_type: str = "regex",
    pattern: str = r"\d{18}",
    action: str = "block",
    severity: str = "critical",
    name: str = "test_rule",
    direction: str = "both",
) -> DlpRule:
    """创建一个测试用的 DLP 规则。"""
    return DlpRule(
        id=uuid4(),
        name=name,
        rule_type=rule_type,
        pattern=pattern,
        action=action,
        severity=severity,
        direction=direction,
        is_active=True,
        priority=0,
        organization_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_regex_rule_blocks_chinese_id():
    """测试正则规则拦截中国身份证号。"""
    rules = [
        _make_rule(
            pattern=r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
            action="block",
            name="chinese_id",
        )
    ]
    engine = DLPEngine(rules=rules)
    result = await engine.scan("我的身份证号是 110101199003077718", direction="request")

    assert result.blocked is True
    assert len(result.violations) == 1
    assert result.violations[0].rule_name == "chinese_id"


@pytest.mark.asyncio
async def test_regex_rule_redacts_email():
    """测试正则规则脱敏邮箱。"""
    rules = [
        _make_rule(
            pattern=r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            action="redact",
            severity="medium",
            name="email_redact",
        )
    ]
    engine = DLPEngine(rules=rules)
    result = await engine.scan("联系邮箱: user@example.com 请求帮助", direction="request")

    assert result.blocked is False
    assert result.redacted_text is not None
    assert "[REDACTED]" in result.redacted_text
    assert "user@example.com" not in result.redacted_text


@pytest.mark.asyncio
async def test_keyword_rule_detects_sensitive_words():
    """测试关键词规则检测敏感词。"""
    rules = [
        _make_rule(
            rule_type="keyword",
            pattern='["绝密", "机密", "秘密"]',
            action="block",
            severity="critical",
            name="sensitive_keywords",
        )
    ]
    engine = DLPEngine(rules=rules)
    result = await engine.scan("这份文件是绝密级别的", direction="request")

    assert result.blocked is True
    assert len(result.violations) == 1


@pytest.mark.asyncio
async def test_direction_filter():
    """测试方向过滤：request-only 规则不匹配 response 扫描。"""
    rules = [
        _make_rule(
            pattern=r"\d{18}",
            action="block",
            direction="request",
            name="request_only",
        )
    ]
    engine = DLPEngine(rules=rules)

    # request 方向应匹配
    result_req = await engine.scan("110101199003077718", direction="request")
    assert result_req.blocked is True

    # response 方向不应匹配
    result_resp = await engine.scan("110101199003077718", direction="response")
    assert result_resp.blocked is False


@pytest.mark.asyncio
async def test_no_rules():
    """没有规则时不应阻止任何内容。"""
    engine = DLPEngine(rules=[])
    result = await engine.scan("任意文本内容", direction="request")

    assert result.blocked is False
    assert result.has_violations is False


@pytest.mark.asyncio
async def test_empty_text():
    """空文本不应触发任何规则。"""
    rules = [_make_rule(pattern=r"\d+", action="block")]
    engine = DLPEngine(rules=rules)
    result = await engine.scan("", direction="request")

    assert result.blocked is False


@pytest.mark.asyncio
async def test_excel_attachment_rule_matches_filename_and_mime():
    """Excel 附件规则应命中文件名扩展名与 MIME 类型，且不误报普通文本。"""
    from app.dlp.patterns.files import EXCEL_ATTACHMENT

    rule = _make_rule(
        pattern=EXCEL_ATTACHMENT["pattern"],
        action=EXCEL_ATTACHMENT["action"],
        severity=EXCEL_ATTACHMENT["severity"],
        direction=EXCEL_ATTACHMENT["direction"],
        name=EXCEL_ATTACHMENT["name"],
    )
    engine = DLPEngine(rules=[rule])

    # 文件名扩展名（含大小写）
    for text in ["请分析 report.xlsx", "附件 data.xls", "budget.XLSX"]:
        result = await engine.scan(text, direction="request")
        assert result.warnings, f"应命中 Excel 附件：{text}"
        assert result.warnings[0].rule_name == "Excel附件"
        assert result.blocked is False  # 默认 warn，不拦截

    # MIME 类型（Anthropic document 块投影后的文本）
    result = await engine.scan(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        direction="request",
    )
    assert result.warnings

    # 普通文本 / 其他格式不应命中
    for text in ["no excel here", "files.pdf", "请查看 readme.md"]:
        result = await engine.scan(text, direction="request")
        assert not result.warnings, f"不应命中：{text}"


def test_extract_text_surfaces_attachment_hints():
    """``_extract_text_surfaces_attachment_hints`` 应将附件块的 media_type/filename 投影到扫描文本。"""
    from app.graph.nodes.dlp import _extract_text_from_messages

    # Anthropic document 块（base64 Excel，无文件名，仅 media_type）
    messages_anthropic = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "帮我分析这份表格"},
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "data": "UEsDBBQ...",
                    },
                },
            ],
        }
    ]
    text = _extract_text_from_messages(messages_anthropic, "anthropic")
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in text
    assert "帮我分析这份表格" in text

    # OpenAI file 块（带 filename）
    messages_openai = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看下这个"},
                {"type": "file", "file": {"filename": "季度报表.xlsx"}},
            ],
        }
    ]
    text = _extract_text_from_messages(messages_openai, "openai")
    assert "季度报表.xlsx" in text

    # 纯字符串 content 仍正常提取
    assert _extract_text_from_messages(
        [{"role": "user", "content": "纯文本消息"}], "openai"
    ) == "纯文本消息"
