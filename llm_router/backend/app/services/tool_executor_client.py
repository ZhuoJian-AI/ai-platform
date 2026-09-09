"""Internal client for the platform-owned, non-extensible tool executor."""

from __future__ import annotations

import time

import httpx

from app.config import settings


def _headers() -> dict[str, str]:
    return {"X-Tool-Executor-Token": settings.tool_executor_token}


async def execute_builtin(
    *,
    tool_kind: str,
    action: str,
    params: dict,
    inputs: list[dict],
    execution_id: str,
    timeout_seconds: int | None = None,
) -> tuple[dict, int]:
    """Execute one registered platform tool; arbitrary scripts are never accepted."""
    started = time.perf_counter()
    execution_timeout = timeout_seconds or settings.tool_executor_timeout_seconds
    payload = {
        "tool_kind": tool_kind,
        "action": action,
        "params": params,
        "inputs": inputs,
        "execution_id": execution_id,
        "timeout_seconds": execution_timeout,
    }
    timeout = settings.tool_executor_queue_wait_seconds + execution_timeout + 15
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{settings.tool_executor_url.rstrip('/')}/execute-builtin",
            json=payload,
            headers=_headers(),
        )
        if response.is_error:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = response.text
            raise RuntimeError(str(detail or f"平台工具执行失败（{response.status_code}）"))
    return response.json(), int((time.perf_counter() - started) * 1000)
