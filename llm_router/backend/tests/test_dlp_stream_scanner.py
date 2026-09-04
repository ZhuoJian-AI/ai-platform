"""DLP 流式扫描器：跨 chunk 脱敏偏移与超时分支的回归测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.dlp import stream_scanner as stream_scanner_module
from app.dlp.stream_scanner import DLPStreamScanner
from app.models.dlp_rule import DlpRule

PHONE = "13800138000"


def _phone_redact_rule() -> DlpRule:
    return DlpRule(
        id=uuid4(),
        name="phone",
        rule_type="regex",
        pattern=r"1[3-9]\d{9}",
        action="redact",
        severity="medium",
        direction="response",
        is_active=True,
        priority=0,
        organization_id=uuid4(),
    )


class _Clock:
    """可控的 monotonic 时钟，避免测试依赖真实等待。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_redaction_offsets_follow_confirmed_offset_across_chunks(monkeypatch):
    """手机号跨两个 chunk、且之前已转发过文本时，仍在正确位置被替换。"""
    clock = _Clock()
    monkeypatch.setattr(stream_scanner_module.time, "monotonic", clock)
    scanner = DLPStreamScanner([_phone_redact_rule()], flush_timeout_ms=200)

    prefix = "前置正文" * 75  # 300 字，超过 256 lookahead → 首块即转发一部分
    emitted = ""
    clock.now = 0.0
    first = await scanner.feed_chunk(prefix)
    emitted += first.emit_text
    assert first.emit_text  # 已有文本被转发，_confirmed_offset > 0
    assert scanner._confirmed_offset > 0

    clock.now = 0.1
    second = await scanner.feed_chunk("电话 " + PHONE[:3])
    emitted += second.emit_text

    clock.now = 0.5  # 超过 flush_timeout_ms → 走超时分支，剩余内容全部转发
    third = await scanner.feed_chunk(PHONE[3:] + " 完")
    emitted += third.emit_text
    emitted += (await scanner.flush()).emit_text

    assert PHONE not in emitted
    assert emitted == prefix + "电话 [REDACTED] 完"


@pytest.mark.asyncio
async def test_first_chunk_after_ttft_is_not_flushed_unredacted(monkeypatch):
    """计时从首个 chunk 开始：TTFT 等待不能让首块未脱敏直接放行。"""
    clock = _Clock()
    monkeypatch.setattr(stream_scanner_module.time, "monotonic", clock)
    clock.now = 0.0
    scanner = DLPStreamScanner([_phone_redact_rule()], flush_timeout_ms=200)

    clock.now = 10.0  # 上游首 token 等了 10 秒
    first = await scanner.feed_chunk("联系方式 " + PHONE)
    emitted = first.emit_text + (await scanner.flush()).emit_text

    assert PHONE not in emitted
    assert emitted == "联系方式 [REDACTED]"


@pytest.mark.asyncio
async def test_block_action_still_terminates_stream():
    rule = _phone_redact_rule()
    rule.action = "block"
    scanner = DLPStreamScanner([rule], flush_timeout_ms=200)
    result = await scanner.feed_chunk("电话 " + PHONE)
    assert result.blocked is True
    assert result.emit_text == ""
