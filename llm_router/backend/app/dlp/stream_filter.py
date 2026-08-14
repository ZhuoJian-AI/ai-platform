"""SSE-aware DLP stream filter — correct per-line filtering that preserves non-content events.

替代 ``app.proxy.stream_handler.wrap_stream_with_dlp``。后者按整 chunk 缓冲，仅在提取到
content 文本时才输出，会把 ``message_start`` / ``message_delta`` / ``usage`` /
``[DONE]`` 等非内容事件与内容事件一并缓冲后丢弃（破坏流式协议）。本过滤器逐行处理 SSE：

- 内容文本增量（Anthropic ``text_delta`` / ``thinking_delta``，OpenAI
  ``choices[].delta.content``）送入 ``DLPStreamScanner``，仅转发扫描器确认安全的文本
  （脱敏后），跨 chunk 边界的部分匹配由扫描器的滑动窗口暂存。
- 其余事件（``message_start`` / ``message_delta`` / ``usage`` / ``[DONE]`` / ``ping`` /
  ``event:`` 头行 / 空行）**逐字透传**，不丢失。
- 命中 ``block`` 规则时发送协议特定的 DLP 拦截事件并终止流。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import structlog

from app.dlp.engine import DLPMatch
from app.dlp.stream_scanner import DLPStreamScanner
from app.proxy.stream_handler import _make_anthropic_dlp_event, _make_openai_dlp_event

logger = structlog.get_logger()


@dataclass
class _Blocked:
    """逐行处理中检测到 block 的哨兵。"""

    violations: list[DLPMatch]


@dataclass
class StreamDlpOutcome:
    """流式 DLP 过滤结果（供调用方做审计/决策）。"""

    blocked: bool = False
    violations: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.violations is None:
            self.violations = []


async def filter_stream_with_dlp(
    upstream: AsyncGenerator[bytes, None],
    scanner: DLPStreamScanner,
    protocol: str,
    outcome: StreamDlpOutcome | None = None,
) -> AsyncGenerator[bytes, None]:
    """消费上游 SSE 字节流，逐行过滤后 yield 安全字节。

    若传入 ``outcome``，命中 block 时会把 ``blocked=True`` 与 violations 写入，供调用方
    （proxy 节点）记录到 state 供审计。
    """
    is_anthropic = protocol == "anthropic"
    line_buf = ""
    blocked = False

    async for raw in upstream:
        chunk = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
        line_buf += chunk
        while "\n" in line_buf:
            line, line_buf = line_buf.split("\n", 1)
            out = await _process_line(line + "\n", scanner, is_anthropic)
            if isinstance(out, _Blocked):
                _record_block(outcome, out.violations)
                yield _make_block_event(out.violations, is_anthropic)
                blocked = True
                break
            if out:
                yield out.encode("utf-8")
        if blocked:
            break

    if not blocked:
        # flush 末尾不完整行
        if line_buf:
            out = await _process_line(line_buf, scanner, is_anthropic)
            if isinstance(out, _Blocked):
                _record_block(outcome, out.violations)
                yield _make_block_event(out.violations, is_anthropic)
                blocked = True
            elif out:
                yield out.encode("utf-8")

    if not blocked:
        # flush 扫描器暂存的滑动窗口文本
        final = await scanner.flush(direction="response")
        if final.blocked:
            _record_block(outcome, final.violations)
            yield _make_block_event(final.violations, is_anthropic)
        elif final.emit_text:
            yield _make_content_event(final.emit_text, is_anthropic)


def _record_block(outcome: StreamDlpOutcome | None, violations: list[DLPMatch]) -> None:
    if outcome is None:
        return
    outcome.blocked = True
    outcome.violations = list(violations)


async def _process_line(line: str, scanner: DLPStreamScanner, is_anthropic: bool) -> str | None | _Blocked:
    """处理单行 SSE，返回待输出文本 / None（跳过） / _Blocked（拦截）。"""
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return line  # event: / 空行 / 注释 → 逐字透传

    payload = stripped[len("data:"):].strip()
    if not payload or payload == "[DONE]":
        return line  # [DONE] 透传

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return line  # 非 JSON 的 data 行透传
    if not isinstance(event, dict):
        return line

    text = _extract_content_text(event, is_anthropic)
    if text is None:
        return line  # 非内容事件 → 透传

    result = await scanner.feed_chunk(text, direction="response")
    if result.blocked:
        return _Blocked(result.violations)
    if result.emit_text:
        new_event = _replace_content_text(event, result.emit_text, is_anthropic)
        return f"data: {json.dumps(new_event, ensure_ascii=False)}\n"
    return None  # 扫描器暂存，本 delta 暂不输出


def _extract_content_text(event: dict, is_anthropic: bool) -> str | None:
    """从单个 SSE 事件中提取内容文本增量；非内容事件返回 None。"""
    if is_anthropic:
        if event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                return delta.get("text", "")
            if delta.get("type") == "thinking_delta":
                return delta.get("thinking", "")
        return None

    choices = event.get("choices") or []
    if choices and isinstance(choices[0], dict):
        delta = choices[0].get("delta") or {}
        if "content" in delta and isinstance(delta["content"], str):
            return delta["content"]
    return None


def _replace_content_text(event: dict, new_text: str, is_anthropic: bool) -> dict:
    """构造内容文本被替换后的新 SSE 事件 dict。"""
    event = dict(event)
    if is_anthropic:
        delta = dict(event.get("delta") or {})
        if delta.get("type") == "text_delta":
            delta["text"] = new_text
        elif delta.get("type") == "thinking_delta":
            delta["thinking"] = new_text
        event["delta"] = delta
    else:
        choices = list(event.get("choices") or [])
        if choices:
            first = dict(choices[0])
            delta = dict(first.get("delta") or {})
            delta["content"] = new_text
            first["delta"] = delta
            choices[0] = first
            event["choices"] = choices
    return event


def _make_block_event(violations: list[DLPMatch], is_anthropic: bool) -> bytes:
    """构造协议特定的 DLP 拦截 SSE 事件。"""
    if is_anthropic:
        return _make_anthropic_dlp_event(violations)
    return _make_openai_dlp_event(violations)


def _make_content_event(emit_text: str, is_anthropic: bool) -> bytes:
    """构造携带 flush 文本的内容增量 SSE 事件。"""
    if is_anthropic:
        event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": emit_text}}
    else:
        event = {"choices": [{"index": 0, "delta": {"content": emit_text}}]}
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
