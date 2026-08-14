"""代理流水线 StateGraph 构建器。

图拓扑：

    START → resolve_permissions ─(越权)─→ build_error ─→ write_audit → END
                     │ (ok)
                     ↓
                 dlp_request ─(blocked)─→ build_error ─→ write_audit → END
                     │ (ok)
                     ↓
                 resolve_route ─(无 provider)─→ build_error ─→ write_audit → END
                     │ (ok)
                     ↓
                 proxy_upstream ─(异常/流式)─→ build_error / write_audit
                     │ (ok, 非流式)
                     ↓
                 dlp_response ─(blocked)─→ build_error ─→ write_audit → END
                     │ (ok)
                     ↓
                  write_audit → END

条件边以 ``state.error`` 是否被设置为准——决策节点在异常分支设置 error，build_error
将其格式化为协议特定响应，write_audit 统一收口写审计。上游调用成功时不设置 error
（错误响应透传给客户端）；流式经 write_audit 收口（响应 DLP 在 proxy 节点内联完成），
非流式经 dlp_response 扫描响应体后进入 write_audit。
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    build_error,
    dlp_request,
    dlp_response,
    proxy_upstream,
    resolve_permissions,
    resolve_route,
    route_after_dlp,
    route_after_dlp_response,
    route_after_perms,
    route_after_proxy,
    route_after_routing,
    write_audit,
)
from app.graph.state import ProxyState


def build_proxy_graph():
    """构建并编译代理流水线 StateGraph（InMemorySaver，按 thread_id 隔离请求）。"""
    graph = StateGraph(ProxyState)

    graph.add_node("resolve_permissions", resolve_permissions)
    graph.add_node("dlp_request", dlp_request)
    graph.add_node("resolve_route", resolve_route)
    graph.add_node("proxy_upstream", proxy_upstream)
    graph.add_node("dlp_response", dlp_response)
    graph.add_node("build_error", build_error)
    graph.add_node("write_audit", write_audit)

    graph.add_edge(START, "resolve_permissions")
    graph.add_conditional_edges(
        "resolve_permissions",
        route_after_perms,
        {"build_error": "build_error", "dlp_request": "dlp_request"},
    )
    graph.add_conditional_edges(
        "dlp_request",
        route_after_dlp,
        {"build_error": "build_error", "resolve_route": "resolve_route"},
    )
    graph.add_conditional_edges(
        "resolve_route",
        route_after_routing,
        {"build_error": "build_error", "proxy_upstream": "proxy_upstream"},
    )
    graph.add_conditional_edges(
        "proxy_upstream",
        route_after_proxy,
        {"build_error": "build_error", "write_audit": "write_audit", "dlp_response": "dlp_response"},
    )
    graph.add_conditional_edges(
        "dlp_response",
        route_after_dlp_response,
        {"build_error": "build_error", "write_audit": "write_audit"},
    )
    graph.add_edge("build_error", "write_audit")
    graph.add_edge("write_audit", END)

    return graph.compile(checkpointer=InMemorySaver())


@lru_cache(maxsize=1)
def get_proxy_graph():
    """进程级单例编译图。InMemorySaver 按 thread_id 隔离各请求状态。"""
    return build_proxy_graph()
