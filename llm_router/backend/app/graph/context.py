"""运行时上下文 —— 注入非序列化依赖（db / Request / auth）。

LangGraph 1.x 中，``ainvoke`` / ``astream`` 接受 ``context=`` 参数；节点内通过
``langgraph.runtime.get_runtime()`` 取得 ``Runtime`` 对象，其 ``.context`` 即传入
的 dict，``.stream_writer`` 即流式写入器。``context`` 不进 checkpoint、按调用注入，
适合传递 db session 等无法序列化的运行时句柄。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.auth.api_key_auth import AuthenticatedKey


class ProxyContext(TypedDict):
    """每次 ainvoke/astream 调用注入的运行时依赖。"""

    db: AsyncSession
    request: Request
    auth: AuthenticatedKey


def get_deps() -> ProxyContext:
    """节点内取得当前请求注入的运行时依赖。"""
    from langgraph.runtime import get_runtime

    runtime = get_runtime()
    return runtime.context  # type: ignore[return-value]


def get_stream_writer() -> Any:
    """节点内取得流式写入器（仅流式分支使用）。"""
    from langgraph.runtime import get_runtime

    return get_runtime().stream_writer
