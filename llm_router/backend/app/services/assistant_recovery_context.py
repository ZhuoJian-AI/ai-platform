"""Bounded historical execution references; never infer success from transport OK."""

from typing import Any


def historical_tool_references(executions: Any) -> list[dict]:
    if not isinstance(executions, list):
        return []
    refs = []
    for item in executions:
        if not isinstance(item, dict):
            continue
        status = str(item.get("resultStatus") or "")[:40]
        ok = item.get("ok") is True
        outcome = str(item.get("executionOutcome") or "")[:40]
        if outcome == "unknown":
            recovery_state = "unknown"
        elif status in {"pending", "needs_confirmation"}:
            recovery_state = "needs_confirmation"
        elif status in {"executing", "queued", "running"}:
            recovery_state = "in_progress"
        elif status == "completed" and ok:
            recovery_state = "completed"
        elif status in {"failed", "error", "retryable_error", "rejected", "cancelled", "expired"} or not ok:
            recovery_state = "not_completed"
        else:
            recovery_state = "unverified"
        refs.append({
            "toolCallId": str(item.get("toolCallId") or "")[:160],
            "name": str(item.get("name") or "")[:160],
            "operation": str(item.get("operation") or "")[:40],
            "ok": ok,
            "resultStatus": status,
            "requestId": str(item.get("requestId") or "")[:160],
            "recoveryState": recovery_state,
        })
    # Recent outcomes are more useful than the first attempts of a long run.
    return refs[-20:]
