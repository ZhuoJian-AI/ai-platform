"""Evidence ledger for attempted operations, not a natural-language intent gate."""

WRITES = {"create", "update", "delete", "approve"}


def operation_outcomes(executions: list[dict]) -> list[dict]:
    rows = {}
    for item in executions:
        kind = item.get("kind")
        if kind not in {"enterprise_action", "subsystem_specialist"}:
            continue
        name = item.get("canonicalName") or item.get("name") or "tool"
        request_id = item.get("requestId") or ""
        key = f"request:{request_id}" if request_id else f"attempt:{name}"
        status = item.get("resultStatus")
        if item.get("executionOutcome") == "unknown":
            outcome = "unknown"
        elif status == "completed" and item.get("ok") is True:
            outcome = "completed"
        elif status in {"pending", "needs_confirmation"}:
            outcome = "needs_confirmation"
        elif status in {"executing", "queued", "running"}:
            outcome = "in_progress"
        else:
            outcome = "not_completed"
        # A schema error with no durable request can be repaired by the next
        # successful call. Never erase another durable operation's unknown result.
        if outcome == "completed":
            rows.pop(f"attempt:{name}", None)
        rows[key] = {"key": key, "name": name, "kind": kind,
                     "displayName": item.get("displayName") or name,
                     "operation": item.get("operation") or "analysis", "requestId": request_id,
                     "status": outcome}
    return list(rows.values())


def unresolved_writes(executions: list[dict]) -> list[dict]:
    return [row for row in operation_outcomes(executions)
            if row["operation"] in WRITES and row["status"] != "completed"]


def final_outcomes(state: dict, artifacts: list) -> list[dict]:
    rows = operation_outcomes(state.get("business_tool_executions") or [])
    if state.get("file_output_required") or state.get("_file_delivery_required"):
        rows.append({"key": "delivery", "kind": "file_delivery", "operation": "deliver",
                     "status": "completed" if artifacts else "not_completed",
                     "artifacts": artifacts})
    return rows
