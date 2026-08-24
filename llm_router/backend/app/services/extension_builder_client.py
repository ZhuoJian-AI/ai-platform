"""Authenticated client for the isolated Node extension builder."""

from __future__ import annotations

import httpx

from app.config import settings


async def build(payload: dict) -> dict:
    timeout = httpx.Timeout(settings.extension_builder_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            f"{settings.extension_builder_url.rstrip('/')}/v1/builds",
            headers={"authorization": f"Bearer {settings.extension_builder_token}"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(f"{settings.extension_builder_url.rstrip('/')}/health")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        return {"status": "unavailable", "error": str(exc)}
