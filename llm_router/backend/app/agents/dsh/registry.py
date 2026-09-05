"""Short-lived, capability-scoped bridge contexts for DSH callbacks.

Besides the run-token → context map used by the model/tool bridges, this module owns the
in-process state for **user approvals**: when the runtime meets a ``ToolSpec.approval="ask"``
tool it calls ``POST /internal/dsh/approval/request``, which parks an ``asyncio.Future`` here
and surfaces ``approval_request`` on the run's SSE channel; the terminal user's decision
(``POST /terminal/tasks/{task_id}/approvals/{approval_id}``) resolves that future.  Single
process, like :mod:`app.agents.graph.run_registry` (one uvicorn worker).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.agents.graph import run_registry as live_runs
from app.agents.graph.state import AgentState

APPROVAL_ALLOWED = "allowed-once"
APPROVAL_REJECTED = "rejected"
APPROVAL_CANCELLED = "cancelled"
APPROVAL_UNAVAILABLE = "unavailable"
APPROVAL_DEFAULT_TIMEOUT_MS = 120_000
APPROVAL_MAX_TIMEOUT_MS = 300_000
# Terminal decision verb → runtime-facing outcome.
APPROVAL_DECISIONS = {"allow": APPROVAL_ALLOWED, "reject": APPROVAL_REJECTED}


class ApprovalNotFoundError(LookupError):
    """Unknown approval id, or its run context already expired / was revoked."""


class ApprovalAlreadyDecidedError(RuntimeError):
    """The approval was already resolved (user decision, timeout or run cancellation)."""


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    tool: str
    call_id: str
    future: asyncio.Future  # resolves to ``(outcome, decided_by)``


@dataclass(slots=True)
class DshRunContext:
    state: AgentState
    db: Any
    deps: dict[str, Any]
    tool_registry: dict[str, dict]
    image_inputs: list[dict[str, str]]
    provider_override: Any = None
    model_override: str | None = None
    expires_at: float = 0.0
    # Live SSE handle + the runner's persisted-event buffer, so bridge callbacks (approvals)
    # reach the terminal user and ``agent_run_events`` exactly like runner-published events.
    handle: live_runs.RunHandle | None = None
    staged: list[dict] | None = None
    # approval_id → record.  Decided records stay until ``revoke`` so a late second decision
    # is reported as "already decided" (409) instead of "unknown" (404).
    approvals: dict[str, ApprovalRecord] = field(default_factory=dict)


_contexts: dict[str, DshRunContext] = {}
_approval_contexts: dict[str, DshRunContext] = {}  # approval_id → owning context


def register(context: DshRunContext) -> str:
    _purge_expired()
    token = secrets.token_urlsafe(32)
    context.expires_at = time.monotonic() + 15 * 60
    _contexts[token] = context
    return token


def get(token: str) -> DshRunContext | None:
    context = _contexts.get(token)
    if context is not None and context.expires_at <= time.monotonic():
        _drop(token)
        return None
    return context


def revoke(token: str) -> None:
    _drop(token)


def _drop(token: str) -> None:
    context = _contexts.pop(token, None)
    if context is not None:
        _cancel_approvals(context)


def _purge_expired() -> None:
    now = time.monotonic()
    for token, context in list(_contexts.items()):
        if context.expires_at <= now:
            _drop(token)


# ── user approvals ───────────────────────────────────────────────────────


def publish_event(context: DshRunContext, event: dict) -> None:
    """Stage ``event`` for persistence and push it to the live SSE tail (mirrors ``runner._publish``)."""
    if context.staged is not None:
        context.staged.append(event)
    if context.handle is not None:
        live_runs.publish(context.handle, json.dumps(event, ensure_ascii=False))


def _resolve(context: DshRunContext, approval_id: str, outcome: str, decided_by: str) -> bool:
    """Settle one approval: wake the waiting bridge call, record the step, publish ``approval_decided``."""
    record = context.approvals.get(approval_id)
    if record is None or record.future.done():
        return False
    record.future.set_result((outcome, decided_by))
    context.state.setdefault("steps", []).append({
        "step": "approval", "tool": record.tool, "outcome": outcome, "decided_by": decided_by,
    })
    publish_event(context, {
        "type": "approval_decided", "approval_id": approval_id, "outcome": outcome, "decided_by": decided_by,
    })
    return True


def _cancel_approvals(context: DshRunContext) -> None:
    for approval_id in list(context.approvals):
        _resolve(context, approval_id, APPROVAL_CANCELLED, "system")
        _approval_contexts.pop(approval_id, None)


def cancel_approvals(token: str) -> None:
    """Resolve every approval still waiting on this run as ``cancelled`` (run stopped / finished)."""
    context = _contexts.get(token)
    if context is not None:
        _cancel_approvals(context)


async def await_approval(
    context: DshRunContext, *, approval_id: str, tool: str, call_id: str, reason: str,
    arguments_preview: str, timeout_ms: int = APPROVAL_DEFAULT_TIMEOUT_MS,
) -> dict[str, str]:
    """Ask the terminal user about one tool call and block until decided, timed out or cancelled.

    Returns ``{"outcome", "decided_by"}`` with outcome ``allowed-once`` / ``rejected`` (user),
    ``rejected`` (timeout), ``cancelled`` (run stopped meanwhile) or ``unavailable`` when the run
    has no live channel or no terminal task that could answer (sync runs, admin playground).
    """
    timeout_ms = max(0, min(int(timeout_ms), APPROVAL_MAX_TIMEOUT_MS))
    record = context.approvals.get(approval_id)
    if record is None:
        record = ApprovalRecord(approval_id, tool, call_id, asyncio.get_running_loop().create_future())
        context.approvals[approval_id] = record
        _approval_contexts[approval_id] = context
        expires_at = datetime.now(UTC) + timedelta(milliseconds=timeout_ms)
        publish_event(context, {
            "type": "approval_request", "approval_id": approval_id, "tool": tool, "call_id": call_id,
            "reason": reason, "arguments_preview": arguments_preview,
            "expires_at": expires_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "run_id": context.state.get("run_id"),
        })
        if context.handle is None or not context.state.get("task_id"):
            _resolve(context, approval_id, APPROVAL_UNAVAILABLE, "system")
    if not record.future.done():
        done, _pending = await asyncio.wait({record.future}, timeout=timeout_ms / 1000)
        if not done:
            _resolve(context, approval_id, APPROVAL_REJECTED, "timeout")
    outcome, decided_by = record.future.result()
    return {"outcome": outcome, "decided_by": decided_by}


def decide_approval(task_id: str, approval_id: str, decision: str) -> str:
    """Terminal user's answer for ``approval_id`` on task ``task_id``; returns the outcome.

    Raises ``ApprovalNotFoundError`` for unknown / expired ids and ids that belong to another task,
    ``ApprovalAlreadyDecidedError`` when the approval was already settled, ``ValueError`` for a
    decision outside ``allow`` / ``reject``.
    """
    outcome = APPROVAL_DECISIONS.get(decision)
    if outcome is None:
        raise ValueError(f"unknown approval decision: {decision!r}")
    context = _approval_contexts.get(approval_id)
    if (
        context is None
        or context.expires_at <= time.monotonic()
        or str(context.state.get("task_id") or "") != str(task_id)
    ):
        raise ApprovalNotFoundError(approval_id)
    record = context.approvals.get(approval_id)
    if record is None:
        raise ApprovalNotFoundError(approval_id)
    if record.future.done():
        raise ApprovalAlreadyDecidedError(approval_id)
    _resolve(context, approval_id, outcome, "user")
    return outcome
