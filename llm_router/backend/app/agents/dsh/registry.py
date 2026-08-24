"""Short-lived, capability-scoped bridge contexts for DSH callbacks."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any

from app.agents.graph.state import AgentState


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


_contexts: dict[str, DshRunContext] = {}


def register(context: DshRunContext) -> str:
    _purge_expired()
    token = secrets.token_urlsafe(32)
    context.expires_at = time.monotonic() + 15 * 60
    _contexts[token] = context
    return token


def get(token: str) -> DshRunContext | None:
    context = _contexts.get(token)
    if context is not None and context.expires_at <= time.monotonic():
        _contexts.pop(token, None)
        return None
    return context


def revoke(token: str) -> None:
    _contexts.pop(token, None)


def _purge_expired() -> None:
    now = time.monotonic()
    for token, context in list(_contexts.items()):
        if context.expires_at <= now:
            _contexts.pop(token, None)
