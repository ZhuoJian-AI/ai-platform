"""代理流水线的请求级运行时上下文。

数据库会话、HTTP 请求和鉴权结果都不能写进可持久化状态，因此通过 ``ContextVar``
随当前异步任务传递。流式写入器也在同一作用域内注入，避免固定代理链依赖通用图运行时。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.auth.api_key_auth import AuthenticatedKey


class ProxyContext(TypedDict):
    """每次代理调用注入的运行时依赖。"""

    db: AsyncSession
    request: Request
    auth: AuthenticatedKey


StreamWriter = Callable[[Any], Awaitable[None]]

_proxy_context: ContextVar[ProxyContext | None] = ContextVar("proxy_context", default=None)
_proxy_stream_writer: ContextVar[StreamWriter | None] = ContextVar(
    "proxy_stream_writer",
    default=None,
)


@contextmanager
def bind_proxy_runtime(
    context: ProxyContext,
    *,
    stream_writer: StreamWriter | None = None,
) -> Iterator[None]:
    """把一次请求的依赖绑定到当前异步执行上下文。"""
    context_token = _proxy_context.set(context)
    writer_token = _proxy_stream_writer.set(stream_writer)
    try:
        yield
    finally:
        _proxy_stream_writer.reset(writer_token)
        _proxy_context.reset(context_token)


def get_deps() -> ProxyContext:
    """节点内取得当前请求注入的运行时依赖。"""
    context = _proxy_context.get()
    if context is None:
        raise RuntimeError("Proxy runtime context is not bound")
    return context


def get_stream_writer() -> StreamWriter:
    """节点内取得流式写入器（仅流式分支使用）。"""
    writer = _proxy_stream_writer.get()
    if writer is None:
        raise RuntimeError("Proxy stream writer is not bound")
    return writer
