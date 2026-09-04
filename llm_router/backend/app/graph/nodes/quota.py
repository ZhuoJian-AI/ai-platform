"""Reserve hierarchical AI quota before the graph contacts a provider."""

from __future__ import annotations

import structlog

from app.graph.context import get_deps
from app.graph.state import ProxyState
from app.services.ai_quota_service import (
    QuotaBackendUnavailableError,
    QuotaConfigurationError,
    QuotaExceededError,
    ensure_output_bound,
    reserve_ai_quota,
)

logger = structlog.get_logger()


async def reserve_quota(state: ProxyState) -> dict:
    deps = get_deps()
    auth = deps["auth"]
    body = state.get("body", {})
    try:
        body, max_output_tokens = ensure_output_bound(
            body,
            state.get("protocol", "openai"),
        )
        reservation = await reserve_ai_quota(
            deps["db"],
            auth.organization_id,
            department_id=auth.department_id,
            team_id=auth.team_id,
            api_key=auth.api_key,
            payload=body,
            max_output_tokens=max_output_tokens,
            request_id=state.get("request_id"),
            provider_id=state.get("provider_id"),
            operation="proxy-chat",
        )
    except QuotaExceededError as exc:
        logger.info(
            "ai_quota_rejected",
            request_id=state.get("request_id"),
            dimension=exc.dimension,
            scope_type=exc.scope_type,
        )
        return {
            "body": body,
            "error": {
                "status_code": 429,
                "error_type": "rate_limit_error",
                "message": f"AI {exc.dimension} limit exceeded at {exc.scope_type} scope",
                "extra": {
                    "quota_dimension": exc.dimension,
                    "quota_scope": exc.scope_type,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            },
        }
    except QuotaBackendUnavailableError:
        return {
            "body": body,
            "error": {
                "status_code": 503,
                "error_type": "service_unavailable",
                "message": "AI quota ledger is unavailable; provider call was not attempted",
                "extra": None,
            },
        }
    except QuotaConfigurationError as exc:
        return {
            "body": body,
            "error": {
                "status_code": 503,
                "error_type": "quota_configuration_error",
                "message": str(exc),
                "extra": None,
            },
        }
    return {"body": body, "quota_reservation": reservation.to_state()}


def route_after_quota(state: ProxyState) -> str:
    return "build_error" if state.get("error") else "proxy_upstream"
