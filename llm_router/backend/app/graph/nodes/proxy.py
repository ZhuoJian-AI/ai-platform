"""proxy_upstream 节点 —— 上游 LLM 调用（httpx 字节透传）。

复用现有 adapter（``proxy_anthropic_request`` / ``proxy_openai_request``）完成实际上游
调用，完整保留 Anthropic/OpenAI 协议细节（thinking / tool_use / prompt caching / 精确
token），Claude Code 与 OpenAI SDK 兼容性零回归。

- **非流式**：adapter 返回 ``Response``，节点提取 body / 状态 / content-type / usage。
- **流式**：adapter 返回 ``StreamingResponse``，节点消费其 ``body_iterator``，逐 chunk
  经 ``get_runtime().stream_writer`` 下发（消费方通过 ``astream(stream_mode="custom")``
  实时取得），同时 ``_StreamUsageTracker`` 累积 token 用量。adapter 自身处理上游错误
  （在流内发送错误 SSE 事件），节点仅透传，不重写协议。

上游调用本身不设置 ``state.error``（错误响应透传给客户端，与原代码一致）；
仅当 adapter 调用抛出意外异常时设置 500 错误。
"""

from __future__ import annotations

import structlog

from app.dlp.scanner import collect_applicable_rules
from app.dlp.stream_filter import filter_stream_with_dlp
from app.dlp.stream_scanner import DLPStreamScanner
from app.graph.context import get_deps, get_stream_writer
from app.graph.state import ProxyState
from app.models.llm_provider import LlmProvider
from app.proxy.anthropic_adapter import proxy_anthropic_request
from app.proxy.openai_adapter import proxy_openai_request
from app.proxy.usage import _StreamUsageTracker, extract_usage_from_body
from app.services.ai_quota_service import settle_ai_quota

logger = structlog.get_logger()


async def proxy_upstream(state: ProxyState) -> dict:
    """调用上游 LLM 提供商，回填响应/用量。"""
    deps = get_deps()
    db = deps["db"]
    request = deps["request"]
    auth = deps["auth"]

    provider = await db.get(LlmProvider, state["provider_id"])
    body = state.get("body", {})
    protocol = state.get("protocol", "openai")
    is_stream = state.get("is_stream", False)
    reservation = state.get("quota_reservation")

    try:
        if protocol == "anthropic":
            response = await proxy_anthropic_request(request, provider, body, auth.api_key.key_prefix)
        else:
            response = await proxy_openai_request(request, provider, body, auth.api_key.key_prefix)
    except Exception as e:  # noqa: BLE001
        logger.error("proxy_upstream_error", request_id=state.get("request_id", ""), error=str(e), exc_info=True)
        return {
            "status_code": 500,
            "upstream_started": True,
            "error": {
                "status_code": 500,
                "error_type": "internal_error",
                "message": f"Internal server error: {e}",
                "extra": None,
            },
        }

    if is_stream:
        # StreamingResponse：消费 body_iterator，逐 chunk 经 writer 下发并累积 usage。
        # 若存在响应方向 DLP 规则，用 SSE 感知过滤器扫描/脱敏内容增量（非内容事件透传）。
        writer = get_stream_writer()
        tracker = _StreamUsageTracker(protocol)
        resp_rules = await collect_applicable_rules(
            db, state.get("org_id", ""), state.get("dept_id"), state.get("team_id"), direction="response"
        )
        upstream = response.body_iterator
        outcome = None
        if resp_rules:
            from app.config import settings
            from app.dlp.stream_filter import StreamDlpOutcome

            scanner = DLPStreamScanner(
                rules=resp_rules,
                buffer_window=settings.dlp_stream_buffer_window,
                flush_timeout_ms=settings.dlp_stream_flush_timeout_ms,
            )
            outcome = StreamDlpOutcome()
            upstream = filter_stream_with_dlp(upstream, scanner, protocol, outcome=outcome)
        completed = False
        try:
            async for chunk in upstream:
                tracker.feed(chunk)
                writer(chunk)
            completed = True
        finally:
            await settle_ai_quota(
                reservation,
                {
                    "input_tokens": tracker.input_tokens,
                    "output_tokens": tracker.output_tokens,
                }
                if completed
                else None,
                db=db,
                outcome="completed" if completed else "disconnected",
            )

        result: dict = {
            "status_code": response.status_code,
            "content_type": response.media_type or "text/event-stream",
            "upstream_started": True,
            "usage": {
                "input_tokens": tracker.input_tokens,
                "output_tokens": tracker.output_tokens,
            },
        }
        # 流式响应 DLP block：拦截事件已发给客户端，此处仅记录供审计（不改 HTTP 状态）
        if outcome and outcome.blocked:
            result["dlp_response_result"] = {
                "blocked": True,
                "violations": [
                    {
                        "rule_name": v.rule_name,
                        "severity": v.severity,
                        "action": v.action,
                        "matched_text_redacted": v.matched_text_redacted,
                    }
                    for v in outcome.violations
                ],
            }
        return result

    # 非流式 Response：透传 body / 状态 / content-type，提取 usage。
    input_tokens, output_tokens = (None, None)
    if response.status_code == 200:
        input_tokens, output_tokens = extract_usage_from_body(response.body, protocol)
    content_type = response.media_type or response.headers.get("content-type", "application/json")
    return {
        "response_body": response.body,
        "status_code": response.status_code,
        "content_type": content_type,
        "upstream_started": True,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def route_after_proxy(state: ProxyState) -> str:
    """上游调用后的条件路由。

    - 意外错误 → build_error
    - 流式（响应 DLP 已在 proxy 节点内联完成）→ write_audit
    - 非流式成功 → dlp_response（扫描响应体）
    """
    if state.get("error"):
        return "build_error"
    if state.get("is_stream"):
        return "write_audit"
    return "dlp_response"
