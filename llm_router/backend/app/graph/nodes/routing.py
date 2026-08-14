"""resolve_route 节点 —— 提供商路由。

等价于原 ``proxy/router.py`` 中「find_provider」这一段。model_alias 直接为真实模型 id
（或 "default" 走组织默认路由），不再有别名解析层。
无可用 provider 时设置 ``state.error``，由条件边导向 build_error。
复用 :mod:`app.routing.router` 的路由算法，不在图中重写。
"""

from __future__ import annotations

import structlog

from app.graph.context import get_deps
from app.graph.state import ProxyState
from app.routing.router import find_provider

logger = structlog.get_logger()


async def resolve_route(state: ProxyState) -> dict:
    """选定上游提供商。"""
    deps = get_deps()
    db = deps["db"]
    org_id = state.get("org_id", "")
    requested_model = state.get("requested_model", "")
    protocol = state.get("protocol", "openai")

    resolved_model = requested_model

    # OpenAI 协议端点优先选 openai 类型 provider；Anthropic 端点优先选 anthropic 类型
    preferred_type = "anthropic" if protocol == "anthropic" else "openai"
    provider = await find_provider(
        db, org_id, resolved_model, preferred_type=preferred_type,
        dept_id=state.get("dept_id"), team_id=state.get("team_id"),
    )
    if provider is None and protocol == "openai":
        # OpenAI 端点回退：不限定 provider 类型
        provider = await find_provider(
            db, org_id, resolved_model,
            dept_id=state.get("dept_id"), team_id=state.get("team_id"),
        )

    if provider is None:
        error_type = "not_found_error" if protocol == "anthropic" else "model_not_found"
        return {
            "resolved_model": resolved_model,
            "error": {
                "status_code": 404,
                "error_type": error_type,
                "message": f"No available provider for model '{resolved_model}'",
                "extra": None,
            },
        }

    # 用解析后的实际模型名替换 body.model，供上游 adapter 使用
    new_body = dict(state.get("body", {}))
    new_body["model"] = resolved_model

    # OpenAI 流式：注入 include_usage 以便上游在末尾 chunk 返回 usage
    if state.get("is_stream") and protocol == "openai":
        stream_opts = new_body.get("stream_options")
        if not isinstance(stream_opts, dict):
            stream_opts = {}
        stream_opts.setdefault("include_usage", True)
        new_body["stream_options"] = stream_opts

    logger.info(
        "proxy_route",
        request_id=state.get("request_id", ""),
        model=resolved_model,
        provider=provider.name,
    )

    return {
        "resolved_model": resolved_model,
        "body": new_body,
        "provider_id": str(provider.id),
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "timeout_seconds": provider.timeout_seconds,
        "max_retries": provider.max_retries,
    }


def route_after_routing(state: ProxyState) -> str:
    """路由后的条件路由：无 provider → build_error，否则 → proxy_upstream。"""
    return "build_error" if state.get("error") else "proxy_upstream"
