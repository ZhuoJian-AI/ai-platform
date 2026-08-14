"""Stream handler — wraps SSE streaming with DLP real-time scanning.

This module intercepts SSE chunks from upstream LLM providers,
feeds them through the DLPStreamScanner, and forwards safe chunks
to the client in real-time.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import structlog

from app.dlp.engine import DLPMatch
from app.dlp.stream_scanner import DLPStreamScanner
from app.models.dlp_rule import DlpRule
from app.models.llm_provider import LlmProvider

logger = structlog.get_logger()


async def wrap_stream_with_dlp(
    upstream_stream: AsyncGenerator[bytes, None],
    rules: list[DlpRule],
    provider: LlmProvider,
    direction: str = "response",
) -> AsyncGenerator[bytes, None]:
    """包装上游 SSE 流，加入 DLP 实时扫描。

    对于每个 SSE chunk:
    1. 解析提取文本内容
    2. 送入 DLPStreamScanner
    3. 根据结果决定转发/拦截/脱敏
    """
    scanner = DLPStreamScanner(rules=rules)
    is_anthropic = provider.provider_type == "anthropic"
    buffer = ""

    async for raw_chunk in upstream_stream:
        chunk_text = raw_chunk.decode("utf-8", errors="replace")
        buffer += chunk_text

        # 尝试从 SSE 事件中提取文本
        text_delta = _extract_text_delta(buffer, is_anthropic)

        if text_delta:
            result = await scanner.feed_chunk(text_delta, direction=direction)

            if result.blocked:
                # 发送 DLP 拦截事件并终止流
                logger.warning("dlp_stream_blocked", violations=len(result.violations))
                if is_anthropic:
                    yield _make_anthropic_dlp_event(result.violations)
                else:
                    yield _make_openai_dlp_event(result.violations)
                return

            if result.emit_text:
                # 替换原始 chunk 中的文本
                modified_chunk = _replace_text_in_chunk(buffer, result.emit_text, is_anthropic)
                yield modified_chunk.encode("utf-8")

            buffer = ""  # 清空已处理的缓冲
        # 如果没有提取到完整文本，继续缓冲

    # 流结束，flush 剩余
    final_result = await scanner.flush(direction=direction)
    if final_result.emit_text:
        yield final_result.emit_text.encode("utf-8")


def _extract_text_delta(sse_buffer: str, is_anthropic: bool) -> str:
    """从 SSE 事件缓冲区中提取文本增量。"""
    if is_anthropic:
        # Anthropic 格式: data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}
        for line in sse_buffer.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            return delta.get("text", "")
                        elif delta.get("type") == "thinking_delta":
                            return delta.get("thinking", "")
                except json.JSONDecodeError:
                    pass
    else:
        # OpenAI 格式: data: {"choices":[{"delta":{"content":"..."}}]}
        for line in sse_buffer.split("\n"):
            if line.startswith("data: ") and line.strip() != "data: [DONE]":
                try:
                    event = json.loads(line[6:])
                    choices = event.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            return content
                except json.JSONDecodeError:
                    pass
    return ""


def _replace_text_in_chunk(original: str, new_text: str, is_anthropic: bool) -> str:
    """替换 SSE chunk 中的文本内容。"""
    if is_anthropic:
        for line in original.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            delta["text"] = new_text
                        elif delta.get("type") == "thinking_delta":
                            delta["thinking"] = new_text
                        return f"data: {json.dumps(event)}\n\n"
                except json.JSONDecodeError:
                    pass
    else:
        for line in original.split("\n"):
            if line.startswith("data: ") and line.strip() != "data: [DONE]":
                try:
                    event = json.loads(line[6:])
                    choices = event.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if "content" in delta:
                            delta["content"] = new_text
                            return f"data: {json.dumps(event)}\n\n"
                except json.JSONDecodeError:
                    pass
    return original


def _make_anthropic_dlp_event(violations: list[DLPMatch]) -> bytes:
    """构造 Anthropic 协议的 DLP 拦截 SSE 事件。"""
    event = {
        "type": "dlp_block",
        "dlp_violations": [
            {
                "rule_name": v.rule_name,
                "severity": v.severity,
                "matched_text_redacted": v.matched_text_redacted,
            }
            for v in violations
        ],
    }
    return f"event: dlp_block\ndata: {json.dumps(event)}\n\n".encode()


def _make_openai_dlp_event(violations: list[DLPMatch]) -> bytes:
    """构造 OpenAI 协议的 DLP 拦截 SSE 事件。"""
    event = {
        "error": {
            "message": "Response blocked by DLP policy",
            "type": "dlp_violation",
            "code": "content_blocked",
            "violations": [
                {
                    "rule_name": v.rule_name,
                    "severity": v.severity,
                    "matched_text_redacted": v.matched_text_redacted,
                }
                for v in violations
            ],
        }
    }
    return f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n".encode()
