"""Persistence and SSE helpers shared by the single DSH coordinator."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from sqlalchemy import select
from starlette.responses import Response, StreamingResponse

from app.agents.graph import run_registry
from app.agents.graph.state import AgentState
from app.auth.admin_auth import CurrentAdmin
from app.auth.user_auth import CurrentUser
from app.database import async_session_factory
from app.models.agent_run import AgentRun, AgentRunEvent

logger = structlog.get_logger()

_SSE_HEADERS = {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-accel-buffering": "no",
}


def initial_state(agent_id: str, org_id: str, message: str, session_id: str | None) -> AgentState:
    return {
        "mode": "agent", "agent_id": agent_id, "org_id": org_id,
        "run_started_monotonic": time.monotonic(),
        "session_id": session_id or f"sess-{uuid.uuid4()}", "request": message,
        "messages": [], "steps": [], "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def general_initial_state(
    *, org_id: str, user: CurrentUser, task_id: str, message: str, session_id: str | None,
    config: dict, attachment_files: list[dict] | None = None,
    invoked_skills: list[dict] | None = None,
) -> AgentState:
    invoked = list(invoked_skills or [])
    return {
        "mode": "general", "org_id": org_id, "task_id": task_id, "user_id": user.id,
        "run_started_monotonic": time.monotonic(),
        "department_id": user.department_id, "team_id": user.team_id,
        "session_id": session_id or f"sess-{uuid.uuid4()}", "request": message,
        "messages": [], "steps": [], "usage": {"input_tokens": 0, "output_tokens": 0},
        "workspace_id": config.get("workspace_id"),
        "skill_ids": list(config.get("skill_ids") or []),
        "invoked_skill_ids": [str(item["id"]) for item in invoked],
        "invoked_skills": invoked, "loaded_skills": [], "executed_skills": [],
        "ontology_ids": list(config.get("ontology_ids") or []),
        "rag_collection_ids": list(config.get("rag_collection_ids") or []),
        "model_alias": config.get("model_alias") or "default",
        "exec_mode": config.get("exec_mode") or "craft",
        "template_agent_id": config.get("template_agent_id"),
        "application_id": config.get("application_id"),
        "page_context": dict(config.get("page_context") or {}),
        "attachment_files": list(attachment_files or []),
        "referenced_file_ids": [str(item["file_id"]) for item in (attachment_files or [])],
    }


def user_message_metadata(initial: AgentState) -> dict:
    metadata: dict = {}
    if attachments := list(initial.get("attachment_files") or []):
        metadata["attachments"] = attachments
    if invoked := list(initial.get("invoked_skills") or []):
        metadata["invoked_skills"] = invoked
    if initial.get("application_id"):
        metadata["application_id"] = initial["application_id"]
    if initial.get("page_context"):
        metadata["page_context"] = initial["page_context"]
    return metadata


def admin_context(db: Any, request: Any, admin: CurrentAdmin) -> dict:
    return {"db": db, "request": request, "admin": admin}


def general_context(db: Any, request: Any, user: CurrentUser, task: Any) -> dict:
    return {"db": db, "request": request, "user": user, "task": task}


async def persist_run_events(
    run_id: int | None, task_id: str, staged: list[dict], final_evt: str | None,
) -> None:
    if run_id is None or (not staged and final_evt is None):
        return
    try:
        async with async_session_factory() as db:
            for index, payload in enumerate(staged, start=1):
                db.add(AgentRunEvent(run_id=run_id, task_id=task_id, seq=index, payload=payload))
            if final_evt is not None:
                db.add(AgentRunEvent(
                    run_id=run_id, task_id=task_id, seq=len(staged) + 1,
                    payload=json.loads(final_evt),
                ))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("dsh_event_persist_failed", task_id=task_id, exc_info=True)


async def finalize_bg_error(
    handle: run_registry.RunHandle, task: Any, run_id: int | None,
    msg: str, run_error: str, session_id: str, start: float,
) -> None:
    err_evt = json.dumps({"type": "error", "message": msg}, ensure_ascii=False)
    final_evt = json.dumps({
        "type": "final", "session_id": session_id, "run_id": run_id,
        "latency_ms": int((time.monotonic() - start) * 1000),
        "interrupted": msg == "cancelled" or "interrupted" in msg,
    }, ensure_ascii=False)
    try:
        async with async_session_factory() as db:
            if run_id is not None:
                run = await db.get(AgentRun, run_id)
                if run is not None and run.status in {"queued", "running"}:
                    lowered = msg.lower()
                    if msg == "cancelled":
                        run.status = "cancelled"
                    elif "排队超过" in msg or "timeout" in lowered:
                        run.status = "timeout"
                    elif "队列已满" in msg or "queue is full" in lowered or "runtime is busy" in lowered:
                        run.status = "busy"
                    else:
                        run.status = "error"
                    run.error = run_error[:500]
            db.add(AgentRunEvent(
                run_id=run_id, task_id=str(task.id), seq=10_000_000,
                payload=json.loads(err_evt),
            ))
            db.add(AgentRunEvent(
                run_id=run_id, task_id=str(task.id), seq=10_000_001,
                payload=json.loads(final_evt),
            ))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("dsh_finalize_persist_failed", task_id=str(task.id), exc_info=True)
    run_registry.mark_done(handle, final_evt, error=run_error)


async def sse_replay_and_tail(handle: run_registry.RunHandle) -> AsyncIterator[str]:
    for payload in list(handle.buffer):
        yield f"data: {payload}\n\n"
    if handle.done:
        return
    handle.attach_reader()
    try:
        while True:
            payload = await handle.queue.get()
            if payload is None:
                break
            yield f"data: {payload}\n\n"
    finally:
        handle.detach_reader()


async def stream_persisted_run(db: Any, run_id: int, *, interrupted: bool = False) -> Response:
    async def body() -> AsyncIterator[str]:
        rows = (await db.execute(
            select(AgentRunEvent).where(AgentRunEvent.run_id == run_id).order_by(AgentRunEvent.seq),
        )).scalars().all()
        for row in rows:
            yield f"data: {json.dumps(row.payload, ensure_ascii=False)}\n\n"
        if interrupted:
            payload = {"type": "final", "run_id": run_id, "interrupted": True}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(body(), status_code=200, media_type="text/event-stream", headers=_SSE_HEADERS)
