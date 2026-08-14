"""Runner —— FastAPI 端点与 LangGraph 智能体图之间的桥接层。

- ``run_agent`` / ``stream_agent``：管理端测试广场（agent 模式），``admin`` 注入 context。
- ``run_general_agent`` / ``stream_general_agent``：终端通用智能体（general 模式），``user`` + ``task``
  注入 context，按任务配置装配资源（workspace/skills/ontology/rag）；长期记忆按用户权限自动载入。

非流式：``graph.ainvoke`` 跑完整图，返回最终 state。流式：返回 ``StreamingResponse``，其
body_iterator 消费 ``graph.astream(stream_mode="custom")``，把节点经 ``stream_writer`` 下发的事件
以 SSE 转发给前端。``thread_id = session_id`` 供 InMemorySaver 按会话隔离状态。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator

import structlog
from sqlalchemy import select
from starlette.responses import Response, StreamingResponse

from app.agents.graph import run_registry
from app.agents.graph.state import AgentState
from app.auth.admin_auth import CurrentAdmin
from app.auth.user_auth import CurrentUser
from app.database import async_session_factory
from app.models.agent_run import AgentRun, AgentRunEvent
from app.models.task import TaskMessage

logger = structlog.get_logger()

_SSE_HEADERS = {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-accel-buffering": "no",
}

# 后台批量落库阈值：攒 N 条 AgentRunEvent commit 一次，避免逐条 commit 开销。
# live tail 走内存 queue 不依赖 DB；DB 落库主要为「run 完成后回放」与「服务重启后孤儿回放」。
_EVENT_FLUSH_BATCH = 25


def _initial_state(agent_id: str, org_id: str, message: str, session_id: str | None) -> AgentState:
    return {
        "mode": "agent",
        "agent_id": agent_id,
        "org_id": org_id,
        "session_id": session_id or f"sess-{uuid.uuid4()}",
        "request": message,
        "messages": [],
        "steps": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _general_initial_state(
    *, org_id: str, user: CurrentUser, task_id: str, message: str, session_id: str | None,
    config: dict,
) -> AgentState:
    """构造 general 模式 initial state：从任务 config 装配资源（空数组=自动匹配，由 load_config 解析）。"""
    return {
        "mode": "general",
        "org_id": org_id,
        "task_id": task_id,
        "user_id": user.id,
        "department_id": user.department_id,
        "team_id": user.team_id,
        "session_id": session_id or f"sess-{uuid.uuid4()}",
        "request": message,
        "messages": [],
        "steps": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "workspace_id": config.get("workspace_id"),
        "skill_ids": list(config.get("skill_ids") or []),
        "ontology_ids": list(config.get("ontology_ids") or []),
        "rag_collection_ids": list(config.get("rag_collection_ids") or []),
        "model_alias": config.get("model_alias") or "default",
        "exec_mode": config.get("exec_mode") or "craft",
        # 可选：引用一个 Agent 行作为「场景模板」，其 system_prompt 作为 persona/policy
        # 前缀拼到 GENERAL_SYSTEM_PROMPT 之前（终端任务借此承载场景 persona + 不可由
        # 本体/目录推导的业务规则 + 输出骨架，用户 composer 只需写目标+对象）。
        "template_agent_id": config.get("template_agent_id"),
    }


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _context(db: Any, request: Any, admin: CurrentAdmin) -> dict:
    return {"db": db, "request": request, "admin": admin}


def _general_context(db: Any, request: Any, user: CurrentUser, task: Any) -> dict:
    return {"db": db, "request": request, "user": user, "task": task}


async def run_agent(
    graph,
    *,
    agent_id: str,
    org_id: str,
    message: str,
    session_id: str | None,
    db: Any,
    request: Any,
    admin: CurrentAdmin,
) -> dict:
    """非流式：跑完整图，返回最终 state 摘要。"""
    start = time.monotonic()
    initial = _initial_state(agent_id, org_id, message, session_id)
    config = _config(initial["session_id"])
    ctx = _context(db, request, admin)

    final = await graph.ainvoke(initial, config=config, context=ctx)
    latency_ms = int((time.monotonic() - start) * 1000)
    return {
        "session_id": initial["session_id"],
        "assistant": final.get("assistant_final", ""),
        "steps": final.get("steps", []),
        "usage": final.get("usage", {}),
        "judge": final.get("judge_result"),
        "error": final.get("error"),
        "run_id": final.get("run_id"),
        "latency_ms": latency_ms,
    }


async def stream_agent(
    graph,
    *,
    agent_id: str,
    org_id: str,
    message: str,
    session_id: str | None,
    db: Any,
    request: Any,
    admin: CurrentAdmin,
) -> Response:
    """流式：SSE 转发 agent_loop 经 stream_writer 下发的事件。"""
    start = time.monotonic()
    initial = _initial_state(agent_id, org_id, message, session_id)
    config = _config(initial["session_id"])
    ctx = _context(db, request, admin)
    session_id_used = initial["session_id"]

    async def body_iterator():
        try:
            async for chunk in graph.astream(initial, config=config, context=ctx, stream_mode="custom"):
                payload = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
                yield f"data: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.error("agent_stream_error", session_id=session_id_used, error=str(exc), exc_info=True)
            err = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        latency_ms = int((time.monotonic() - start) * 1000)
        final_evt = json.dumps(
            {"type": "final", "session_id": session_id_used, "latency_ms": latency_ms},
            ensure_ascii=False,
        )
        yield f"data: {final_evt}\n\n"

    return StreamingResponse(
        body_iterator(),
        status_code=200,
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "connection": "keep-alive", "x-accel-buffering": "no"},
    )


async def run_general_agent(
    graph,
    *,
    org_id: str,
    user: CurrentUser,
    task: Any,
    message: str,
    config: dict,
    session_id: str | None,
    db: Any,
    request: Any,
) -> dict:
    """非流式：终端通用智能体执行，返回最终 state 摘要。"""
    start = time.monotonic()
    initial = _general_initial_state(org_id=org_id, user=user, task_id=str(task.id),
                                     message=message, session_id=session_id, config=config)
    lg_config = _config(initial["session_id"])
    ctx = _general_context(db, request, user, task)

    # 起始即落 user 消息（与流式 _run_graph_bg 一致）：save_memory 收尾只补 assistant。
    try:
        db.add(TaskMessage(task_id=task.id, role="user", content=initial.get("request", "")))
        await db.flush()
    except Exception:  # noqa: BLE001
        logger.warning("general_usermsg_persist_failed", task_id=str(task.id), exc_info=True)

    final = await graph.ainvoke(initial, config=lg_config, context=ctx)
    latency_ms = int((time.monotonic() - start) * 1000)
    return {
        "session_id": initial["session_id"],
        "assistant": final.get("assistant_final", ""),
        "steps": final.get("steps", []),
        "usage": final.get("usage", {}),
        "memory_extracted": sum(
            1 for s in (final.get("steps") or []) if isinstance(s, dict) and s.get("step") == "extract_memory"
        ),
        "error": final.get("error"),
        "run_id": final.get("run_id"),
        "latency_ms": latency_ms,
    }


async def stream_general_agent(
    graph,
    *,
    org_id: str,
    user: CurrentUser,
    task: Any,
    message: str,
    config: dict,
    session_id: str | None,
    db: Any,
    request: Any,
) -> Response:
    """流式：终端通用智能体执行——后台 detach 跑，SSE 回放 + 续接 live。

    执行与 SSE 连接解耦：图在 ``asyncio.create_task`` 后台跑（独立 session），事件边产边
    入 run_registry（内存 buffer + queue）+ 落 agent_run_events 表。SSE 响应只读 registry：
    先回放历史 buffer，再 tail queue 到 done。客户端断连只停读，run 继续；重连/刷新走 resume
    端点（见 terminal.py GET /stream）或再次 POST /run（registry 有 active handle = 重连）。
    """
    task_id = str(task.id)
    session_id_used = session_id or f"sess-{uuid.uuid4()}"

    handle = run_registry.get(task_id)
    if handle is None or handle.done:
        # 起新 run：注册 handle + detach 后台 runner
        handle = run_registry.get_or_register(task_id)
        initial = _general_initial_state(
            org_id=org_id, user=user, task_id=task_id,
            message=message, session_id=session_id_used, config=config,
        )
        lg_config = _config(initial["session_id"])
        bg_task = asyncio.create_task(
            _run_graph_bg(
                handle, graph, initial=initial, lg_config=lg_config,
                org_id=org_id, user=user, task=task, session_id=initial["session_id"],
            ),
            name=f"agent_run:{task_id}",
        )
        handle.bg_task = bg_task
    # 无论新起还是重连，都走同一回放+tail body
    return StreamingResponse(
        _sse_replay_and_tail(handle), status_code=200, media_type="text/event-stream", headers=_SSE_HEADERS,
    )


async def _run_graph_bg(
    handle: "run_registry.RunHandle", graph, *, initial: AgentState, lg_config: dict,
    org_id: str, user: CurrentUser, task: Any, session_id: str,
) -> None:
    """后台执行图：独立 session，消费 graph.astream 事件，publish + 落库 + 收口。

    照搬 ``app/services/rag_service.py:_run_ingest_bg`` 的「自带 async_session_factory」范式。
    """
    ctx = {"db": None, "request": None, "user": user, "task": task}
    start = time.monotonic()
    seq = 0
    run_id: int | None = None
    # 事件先暂存内存，结束时再批量落库：避免 consumer 任务与本会话（图节点也在用）并发
    # 触发 asyncpg「another operation is in progress」。live SSE 仍由 run_registry.publish
    # 内存 buffer + queue 即时下发，不受影响；只是 agent_run_events 表行延后到 run 收口时落。
    staged: list[dict] = []
    try:
        async with async_session_factory() as db:
            ctx["db"] = db
            # 起始即落本轮 user 消息并提交：run 期间 GET /tasks/{id} 能带回这条提示词，
            # 切走/刷新重连回放时前面才有用户消息（否则要等到收尾 save_memory 才落库，
            # 运行中重连看不到提示词；且 run 在 persist 前崩溃会连用户消息一起丢）。
            # 收尾 save_memory 只补 assistant，不重复落 user。
            try:
                db.add(TaskMessage(task_id=task.id, role="user",
                                   content=initial.get("request", "")))
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.warning("general_bg_usermsg_persist_failed",
                               task_id=str(task.id), exc_info=True)
            async for chunk in graph.astream(initial, config=lg_config, context=ctx, stream_mode="custom"):
                payload = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
                seq += 1
                # 首事件 load_config 带 run_id（nodes.py load_config 已在该节点内提交 run 行），
                # 据此填 handle.run_id；此处不再提交 graph 会话，避免与后续节点 DB 调用争用同连接。
                if run_id is None:
                    try:
                        evt = json.loads(payload)
                        rid = evt.get("run_id") if evt.get("type") == "step" else None
                        if rid is not None:
                            run_id = int(rid)
                            handle.run_id = run_id
                    except (ValueError, TypeError):
                        pass
                run_registry.publish(handle, payload)
                try:
                    payload_dict = json.loads(payload)
                except (ValueError, TypeError):
                    payload_dict = {"raw": payload}
                staged.append(payload_dict)
            # 图正常结束：write_run_log 节点已在同会话置 agent_runs.status。
            # 提交 graph 会话的所有写入（memory facts / write_run_log 状态 / audit 等）。
            latency_ms = int((time.monotonic() - start) * 1000)
            final_evt = json.dumps(
                {"type": "final", "session_id": session_id, "run_id": run_id, "latency_ms": latency_ms},
                ensure_ascii=False,
            )
            try:
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.warning("general_bg_commit_failed", task_id=str(task.id), exc_info=True)
            # 事件落库用独立会话（run 行已由 load_config 提交，FK 安全；与 graph 会话连接隔离）。
            await _persist_run_events(run_id, str(task.id), staged, final_evt)
            run_registry.mark_done(handle, final_evt)
    except asyncio.CancelledError:
        # 前端 Stop / shutdown：标 run 取消 + 投递 error/final
        await _persist_run_events(run_id, str(task.id), staged, None)
        await _finalize_bg_error(handle, task, run_id, "cancelled", "cancelled by user/shutdown", session_id, start)
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("general_bg_error", task_id=str(task.id), error=str(exc), exc_info=True)
        # 异常前已暂存的事件也落库（run 行已由 load_config 提交，FK 安全），便于事后回放定位崩溃点。
        await _persist_run_events(run_id, str(task.id), staged, None)
        await _finalize_bg_error(handle, task, run_id, str(exc)[:500], str(exc), session_id, start)
    finally:
        # 句柄留到 mark_done 之后；done 后从注册表移除，避免内存泄漏。
        # 注意：live 读者在 _sse_replay_and_tail 里已通过 queue 收到哨兵退出；drop 不影响其已读内容。
        if handle.done:
            run_registry.drop(str(task.id))


async def _persist_run_events(
    run_id: int | None, task_id: str, staged: list[dict], final_evt: str | None,
) -> None:
    """把内存暂存的事件批量落 agent_run_events 表。

    用独立会话（与图执行会话隔离），run 行已由 ``load_config`` 提交故 run_id 外键安全。
    ``final_evt`` 非空时附作末条（seq = len(staged)+1）；为空（崩溃/取消路径）则只落已暂存事件，
    末条 error/final 由 ``_finalize_bg_error`` 以高位 seq 补写。失败仅告警，不阻断收口。
    """
    if run_id is None or not staged and final_evt is None:
        return
    try:
        async with async_session_factory() as db:
            for i, payload in enumerate(staged, start=1):
                db.add(AgentRunEvent(
                    run_id=run_id, task_id=task_id, seq=i, payload=payload,
                ))
            if final_evt is not None:
                db.add(AgentRunEvent(
                    run_id=run_id, task_id=task_id, seq=len(staged) + 1,
                    payload=json.loads(final_evt),
                ))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("general_bg_event_persist_failed", task_id=task_id, exc_info=True)


async def _finalize_bg_error(
    handle: "run_registry.RunHandle", task: Any, run_id: int | None,
    msg: str, run_error: str, session_id: str, start: float,
) -> None:
    """后台 runner 异常/取消收口：投递 error + final，并把 agent_runs.status 改 error。

    用独立 session（主会话此时已在 CancelledError 中毒/回滚）。落库 error/final 用高位 seq
    保证回放时排在真实事件之后。
    """
    err_evt = json.dumps({"type": "error", "message": msg}, ensure_ascii=False)
    latency_ms = int((time.monotonic() - start) * 1000)
    final_evt = json.dumps(
        {"type": "final", "session_id": session_id, "run_id": run_id, "latency_ms": latency_ms,
         "interrupted": msg == "cancelled" or "interrupted" in msg},
        ensure_ascii=False,
    )
    try:
        async with async_session_factory() as db:
            if run_id is not None:
                run = await db.get(AgentRun, run_id)
                if run is not None and run.status == "running":
                    run.status = "error"
                    run.error = run_error[:500]
            db.add(AgentRunEvent(run_id=run_id, task_id=str(task.id), seq=10_000_000,
                                 payload=json.loads(err_evt)))
            db.add(AgentRunEvent(run_id=run_id, task_id=str(task.id), seq=10_000_001,
                                 payload=json.loads(final_evt)))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("general_bg_finalize_persist_failed", task_id=str(task.id), exc_info=True)
    run_registry.mark_done(handle, final_evt, error=run_error)


async def _sse_replay_and_tail(handle: "run_registry.RunHandle") -> AsyncIterator[str]:
    """live handle 的 SSE body：回放历史 buffer → tail queue 到 done 哨兵。"""
    # 回放历史（含已 final，若 done）
    for payload in list(handle.buffer):
        yield f"data: {payload}\n\n"
    if handle.done:
        return
    handle.attach_reader()
    try:
        while True:
            payload = await handle.queue.get()
            if payload is None:  # mark_done 投递的哨兵
                break
            yield f"data: {payload}\n\n"
    finally:
        handle.detach_reader()


async def stream_persisted_run(db: Any, run_id: int, *, interrupted: bool = False) -> Response:
    """resume 端点用：回放已完成（或孤儿）run 的落库事件，可选补合成 final。

    interrupted=True 时（孤儿 run 被标 error），末尾补 ``final interrupted`` 让前端收尾。
    """
    async def body() -> AsyncIterator[str]:
        rows = (await db.execute(
            select(AgentRunEvent).where(AgentRunEvent.run_id == run_id).order_by(AgentRunEvent.seq)
        )).scalars().all()
        for r in rows:
            yield f"data: {json.dumps(r.payload, ensure_ascii=False)}\n\n"
        if interrupted:
            yield f"data: {json.dumps({'type': 'final', 'run_id': run_id, 'interrupted': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(body(), status_code=200, media_type="text/event-stream", headers=_SSE_HEADERS)


async def stream_general_agent_legacy_compat(*_args: Any, **_kwargs: Any) -> Response:  # pragma: no cover
    """占位：旧签名兼容，不应再被调用。"""
    raise RuntimeError("stream_general_agent 已重构为 detach 模式，请用 stream_general_agent")
