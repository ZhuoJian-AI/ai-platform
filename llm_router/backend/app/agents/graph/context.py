"""Context-local non-serializable dependencies for one Assistant Core run."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.auth.admin_auth import CurrentAdmin
    from app.auth.user_auth import CurrentUser
    from app.models.task import Task


class AgentContext(TypedDict):
    """每次 Assistant Core run 注入的运行时依赖。

    admin 用于管理端 playground（agent 模式）；user + task 用于终端通用智能体（general 模式）。
    二者按调用场景择一注入，故均 NotRequired。
    """

    db: AsyncSession
    request: Request
    admin: NotRequired[CurrentAdmin]
    user: NotRequired[CurrentUser]
    task: NotRequired[Task]


_local_deps: ContextVar[AgentContext | None] = ContextVar("agent_local_deps", default=None)
_local_writer: ContextVar[Any | None] = ContextVar("agent_local_writer", default=None)


@contextmanager
def bind_runtime(deps: AgentContext, writer: Any | None = None) -> Iterator[None]:
    """Bind dependencies for platform capability preparation and callbacks.

    The Python capability catalog remains the implementation boundary. Context variables
    let capability functions keep one stable dependency API without global mutable state.
    """
    deps_token = _local_deps.set(deps)
    writer_token = _local_writer.set(writer)
    try:
        yield
    finally:
        _local_writer.reset(writer_token)
        _local_deps.reset(deps_token)


def get_deps() -> AgentContext:
    """取得当前 Assistant Core 运行对应的平台依赖。"""
    local = _local_deps.get()
    if local is not None:
        return local
    raise RuntimeError("agent platform capabilities require a bound Assistant Core context")


def get_stream_writer() -> Any:
    """取得当前 Assistant Core 运行的事件写入器。"""
    local = _local_writer.get()
    if local is not None:
        return local
    raise RuntimeError("agent platform capabilities require a bound Assistant Core event writer")
