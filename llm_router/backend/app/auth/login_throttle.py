"""Small Redis-backed throttle for public password and MFA entry points."""

from __future__ import annotations

import hashlib

import structlog
from fastapi import HTTPException
from redis.asyncio import Redis

from app.config import settings

logger = structlog.get_logger()


def _keys(namespace: str, identity: str, source: str) -> tuple[str, str]:
    identity_hash = hashlib.sha256(identity.strip().lower().encode("utf-8")).hexdigest()
    source_hash = hashlib.sha256((source or "unknown").encode("utf-8")).hexdigest()
    prefix = f"auth-throttle:{namespace}"
    return f"{prefix}:account:{identity_hash}", f"{prefix}:source:{source_hash}"


async def _client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


async def assert_login_allowed(namespace: str, identity: str, source: str) -> None:
    if settings.is_development:
        return
    client = await _client()
    try:
        values = await client.mget(_keys(namespace, identity, source))
        if any(int(value or 0) >= settings.login_failure_limit for value in values):
            raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - authentication remains available during Redis recovery
        logger.warning("login_throttle_unavailable", error=str(exc)[:200])
    finally:
        await client.aclose()


async def record_login_failure(namespace: str, identity: str, source: str) -> None:
    if settings.is_development:
        return
    client = await _client()
    try:
        pipeline = client.pipeline(transaction=True)
        for key in _keys(namespace, identity, source):
            pipeline.incr(key)
            pipeline.expire(key, settings.login_failure_window_seconds)
        await pipeline.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("login_throttle_unavailable", error=str(exc)[:200])
    finally:
        await client.aclose()


async def clear_login_failures(namespace: str, identity: str, source: str) -> None:
    if settings.is_development:
        return
    client = await _client()
    try:
        await client.delete(*_keys(namespace, identity, source))
    except Exception as exc:  # noqa: BLE001
        logger.warning("login_throttle_unavailable", error=str(exc)[:200])
    finally:
        await client.aclose()
