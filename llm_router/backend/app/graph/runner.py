"""Runner —— FastAPI endpoint 与 LangGraph 之间的桥接层。

- ``run_proxy``：非流式，``graph.ainvoke`` 跑完整图后由最终 state 构造 ``Response``。
- ``stream_proxy``：流式，返回 ``StreamingResponse``，其 body_iterator 消费
  ``graph.astream(stream_mode="custom")``，将 proxy 节点经 ``stream_writer`` 下发的
  chunk 实时转发给客户端。流结束后图自动完成 write_audit（消费方迭代至结束即图完成）。

``context`` 注入 db session / Request / auth（非序列化，不进 checkpoint）；
``thread_id = request_id`` 供 InMemorySaver 按请求隔离状态。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from starlette.responses import Response, StreamingResponse

from app.auth.api_key_auth import AuthenticatedKey
from app.graph.state import ProxyState

logger = structlog.get_logger()


def _initial_state(body: dict, protocol: str, is_stream: bool) -> ProxyState:
    return {
        "request_id": str(uuid.uuid4()),
        "protocol": protocol,
        "is_stream": is_stream,
        "start_time": time.monotonic(),
        "body": body,
        "requested_model": body.get("model", "") or "",
    }


def _config(request_id: str) -> dict:
    return {"configurable": {"thread_id": request_id}}


def _context(db: Any, request: Any, auth: AuthenticatedKey) -> dict:
    return {"db": db, "request": request, "auth": auth}


async def run_proxy(
    graph,
    *,
    request: Any,
    auth: AuthenticatedKey,
    db: Any,
    body: dict,
    protocol: str,
) -> Response:
    """非流式：跑完整图，由最终 state 构造 HTTP 响应。"""
    initial = _initial_state(body, protocol, is_stream=False)
    config = _config(initial["request_id"])
    ctx = _context(db, request, auth)

    final = await graph.ainvoke(initial, config=config, context=ctx)

    return Response(
        content=final.get("response_body", b""),
        status_code=final.get("status_code", 200),
        media_type=final.get("content_type", "application/json"),
    )


async def stream_proxy(
    graph,
    *,
    request: Any,
    auth: AuthenticatedKey,
    db: Any,
    body: dict,
    protocol: str,
) -> Response:
    """流式：先跑决策段，再按结果返回错误响应或流式响应。

    为与原代码语义一致（DLP block / 模型越权 / 无 provider 等早错误在进入流前即
    返回错误 JSON，而非空 200 流），采用 LangGraph ``interrupt_before`` 模式：

    1. ``ainvoke(interrupt_before=["proxy_upstream"])`` 跑 resolve_permissions →
       dlp_request → resolve_route，在 proxy 前停住。
       - 若早错误：build_error + write_audit 跑完，图到达 END（``next`` 为空），
         返回 build_error 构造的错误 Response。
       - 否则：图停在 proxy 前（``next == ("proxy_upstream",)``），进入步骤 2。
    2. ``astream(None, stream_mode="custom")`` 从 checkpoint 恢复，跑 proxy_upstream
       （经 stream_writer 实时下发 chunk）→ write_audit，返回 StreamingResponse。
    """
    initial = _initial_state(body, protocol, is_stream=True)
    config = _config(initial["request_id"])
    ctx = _context(db, request, auth)
    request_id = initial["request_id"]

    # 1. 决策段（到 proxy 前停住）
    await graph.ainvoke(initial, config=config, context=ctx, interrupt_before=["proxy_upstream"])
    snapshot = graph.get_state(config)

    # 早错误路径：图已跑完，build_error 已构造错误响应
    if not snapshot.next:
        values = snapshot.values or {}
        return Response(
            content=values.get("response_body", b""),
            status_code=values.get("status_code", 200),
            media_type=values.get("content_type", "application/json"),
        )

    # 2. happy path：恢复执行，流式转发 proxy 下发的 chunk
    async def body_iterator():
        try:
            async for chunk in graph.astream(None, config=config, context=ctx, stream_mode="custom"):
                if isinstance(chunk, (bytes, bytearray)):
                    yield bytes(chunk)
                elif isinstance(chunk, str):
                    yield chunk.encode("utf-8")
                else:
                    # writer 收到的非字节载荷（不应发生于透传路径），跳过
                    logger.warning(
                        "proxy_stream_unexpected_chunk",
                        request_id=request_id,
                        chunk_type=type(chunk).__name__,
                    )
        except Exception as e:  # noqa: BLE001
            logger.error("proxy_stream_error", request_id=request_id, error=str(e), exc_info=True)

    return StreamingResponse(
        body_iterator(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )
