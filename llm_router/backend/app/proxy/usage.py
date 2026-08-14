"""Token usage extraction for proxy metering.

从上游响应中提取 token 用量，供审计日志与预算统计：
- 非流式：解析响应体 JSON 的 ``usage`` 字段
- 流式：解析 SSE ``data:`` 行累积 usage
  - OpenAI：仅在 ``stream_options.include_usage=true`` 时于末尾 chunk 出现 usage
  - Anthropic：``message_start`` 含 input_tokens，``message_delta`` 含 output_tokens

注意：SSE chunk 可能在任意字节处断开，``_StreamUsageTracker`` 维护行缓冲按 ``\\n`` 切分。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from starlette.responses import StreamingResponse


def _extract_usage_obj(data: dict, protocol: str) -> tuple[int | None, int | None]:
    """从普通 usage 对象提取 (input_tokens, output_tokens)。"""
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None, None
    if protocol == "openai":
        return usage.get("prompt_tokens"), usage.get("completion_tokens")
    # anthropic 非流式：usage.input_tokens / usage.output_tokens
    return usage.get("input_tokens"), usage.get("output_tokens")


def extract_usage_from_body(body: bytes, protocol: str) -> tuple[int | None, int | None]:
    """从非流式响应体提取 (input_tokens, output_tokens)。解析失败返回 (None, None)。"""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    return _extract_usage_obj(data, protocol)


def _extract_stream_event(data: dict, protocol: str) -> tuple[int | None, int | None]:
    """从单个 SSE 事件 JSON 提取 token（仅返回本次事件能确定的字段，另一项为 None）。"""
    if protocol == "openai":
        return _extract_usage_obj(data, protocol)

    # anthropic：usage 分散在两类事件中
    etype = data.get("type")
    if etype == "message_start":
        usage = (data.get("message") or {}).get("usage") or {}
        return usage.get("input_tokens"), None
    if etype == "message_delta":
        usage = data.get("usage") or {}
        return None, usage.get("output_tokens")
    return None, None


class _StreamUsageTracker:
    """累积解析 SSE 流中的 token 用量。"""

    def __init__(self, protocol: str) -> None:
        self.protocol = protocol
        self._buf = b""
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None

    def feed(self, chunk: bytes) -> None:
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._process_line(line)

    def _process_line(self, line: bytes) -> None:
        s = line.strip()
        if not s.startswith(b"data:"):
            return
        payload = s[len(b"data:"):].strip()
        if not payload or payload == b"[DONE]":
            return
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        in_t, out_t = _extract_stream_event(data, self.protocol)
        if in_t is not None:
            self.input_tokens = in_t
        if out_t is not None:
            self.output_tokens = out_t


def wrap_streaming_with_usage(
    response: StreamingResponse,
    protocol: str,
    on_done: Callable[[int | None, int | None], Awaitable[None]],
) -> StreamingResponse:
    """包装 StreamingResponse：透传字节流并解析 SSE 累积用量，流结束后回调 on_done。

    ``on_done(input_tokens, output_tokens)`` 通常用于在流结束后写入审计日志
    （此时 get_db 依赖尚未退出，session 仍可写，commit 由依赖退出时完成）。
    """
    tracker = _StreamUsageTracker(protocol)
    orig = response.body_iterator

    async def _tracked():
        try:
            async for chunk in orig:
                tracker.feed(chunk)
                yield chunk
        finally:
            await on_done(tracker.input_tokens, tracker.output_tokens)

    # content-type 由 media_type 设置，避免重复；其余头（cache-control 等）保留
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-type"}
    return StreamingResponse(
        _tracked(),
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )
