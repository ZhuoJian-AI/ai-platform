"""运行时上下文 —— 注入非序列化依赖（db / admin）。

与 app.graph.context 同范式：LangGraph 1.x 的 ``ainvoke`` / ``astream`` 接受 ``context=``；
节点内经 ``langgraph.runtime.get_runtime()`` 取得 Runtime，其 ``.context`` 即注入的 dict，
``.stream_writer`` 即流式写入器。context 不进 checkpoint、按调用注入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.auth.admin_auth import CurrentAdmin
    from app.auth.user_auth import CurrentUser
    from app.models.task import Task


class AgentContext(TypedDict):
    """每次 ainvoke/astream 调用注入的运行时依赖。

    admin 用于管理端 playground（agent 模式）；user + task 用于终端通用智能体（general 模式）。
    二者按调用场景择一注入，故均 NotRequired。
    """

    db: AsyncSession
    request: Request
    admin: NotRequired["CurrentAdmin"]
    user: NotRequired["CurrentUser"]
    task: NotRequired["Task"]


def get_deps() -> AgentContext:
    """节点内取得当前请求注入的运行时依赖。"""
    from langgraph.runtime import get_runtime

    runtime = get_runtime()
    return runtime.context  # type: ignore[return-value]


def get_stream_writer() -> Any:
    """节点内取得流式写入器（测试广场流式分支使用）。"""
    from langgraph.runtime import get_runtime

    return get_runtime().stream_writer
