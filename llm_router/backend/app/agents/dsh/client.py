"""HTTP/NDJSON client for the internal DSH Runtime service."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings


def _headers() -> dict[str, str]:
    return {"authorization": f"Bearer {settings.dsh_runtime_token}"}


async def stream_run(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    timeout = httpx.Timeout(settings.dsh_runtime_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", f"{settings.dsh_runtime_url.rstrip('/')}/v1/runs",
            headers={**_headers(), "content-type": "application/json"}, json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    yield json.loads(line)


async def cancel_run(run_id: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.dsh_runtime_url.rstrip('/')}/v1/runs/{run_id}/cancel",
                headers=_headers(),
            )
        return response.status_code in {200, 202}
    except httpx.HTTPError:
        return False
