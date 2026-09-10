"""Provider-neutral assistant tool descriptors and result envelopes."""

from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

ToolResultStatus = Literal[
    "completed",
    "needs_input",
    "needs_confirmation",
    "retryable_error",
    "failed",
]


class ToolError(TypedDict, total=False):
    code: str
    messageZh: str
    correctionFields: list[dict[str, Any]]
    retryable: bool


class ToolResultEnvelope(TypedDict, total=False):
    status: ToolResultStatus
    data: Any
    artifacts: list[dict[str, Any]]
    uiIntent: dict[str, Any] | None
    error: ToolError | None


def tool_result(
    status: ToolResultStatus,
    *,
    data: Any = None,
    artifacts: list[dict[str, Any]] | None = None,
    ui_intent: dict[str, Any] | None = None,
    error: ToolError | None = None,
) -> ToolResultEnvelope:
    """Build the one result shape consumed by every Assistant Core adapter."""

    return {
        "status": status,
        "data": data,
        "artifacts": list(artifacts or []),
        "uiIntent": ui_intent,
        "error": error,
    }


def tool_result_json(
    status: ToolResultStatus,
    *,
    data: Any = None,
    artifacts: list[dict[str, Any]] | None = None,
    ui_intent: dict[str, Any] | None = None,
    error: ToolError | None = None,
) -> str:
    return json.dumps(
        tool_result(
            status,
            data=data,
            artifacts=artifacts,
            ui_intent=ui_intent,
            error=error,
        ),
        ensure_ascii=False,
        default=str,
    )


def descriptor_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Project one runtime ToolSpec into the documented AssistantToolDescriptor."""

    return {
        "name": str(spec.get("name") or ""),
        "description": str(spec.get("description") or ""),
        "inputSchema": spec.get("input_schema") or {"type": "object", "properties": {}},
        "outputSchema": spec.get("output_schema") or {"type": "object"},
        "riskLevel": str(spec.get("risk_level") or "low"),
        "requiredRolePermissions": list(spec.get("required_role_permissions") or []),
        "requiredContext": spec.get("required_context") or None,
        "modelCapabilityBinding": spec.get("model_capability_binding") or None,
        "idempotencyPolicy": str(spec.get("idempotency_policy") or "run_tool_call"),
        "confirmationPolicy": str(spec.get("confirmation_policy") or "never"),
        "artifactPolicy": str(spec.get("artifact_policy") or "none"),
    }
