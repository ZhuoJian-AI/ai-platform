"""build_error 节点 —— 将协议无关的 error reason 格式化为协议特定的错误响应。

决策节点（resolve_permissions / dlp_request / resolve_route / proxy_upstream 异常分支）
设置 ``state.error = {"status_code", "error_type", "message", "extra"}``（协议无关），
本节点按当前协议调用 ``make_anthropic_error`` / ``make_openai_error`` 生成最终响应体，
回填 ``response_body`` / ``status_code`` / ``content_type``，供 runner 构造 HTTP 响应。
复用 adapter 的错误构造函数，保证载荷与原代码逐字节一致。
"""

from __future__ import annotations

from app.graph.state import ProxyState
from app.proxy.anthropic_adapter import make_anthropic_error
from app.proxy.openai_adapter import make_openai_error


async def build_error(state: ProxyState) -> dict:
    """把 state.error 格式化为协议特定的错误响应字段。"""
    err = state.get("error")
    if not err:
        return {}

    protocol = state.get("protocol", "openai")
    status_code = err.get("status_code", 500)
    error_type = err.get("error_type", "internal_error")
    message = err.get("message", "")
    extra = err.get("extra")

    if protocol == "anthropic":
        response = make_anthropic_error(status_code, error_type, message, extra=extra)
    else:
        response = make_openai_error(status_code, error_type, message, extra=extra)

    return {
        "response_body": response.body,
        "status_code": response.status_code,
        "content_type": response.media_type,
    }
