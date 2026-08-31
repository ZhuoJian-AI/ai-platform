"""Authentication for least-privilege ECS runtime publisher credentials."""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ecs_runtime import EcsRuntime
from app.utils.crypto import hash_api_key

RUNTIME_CREDENTIAL_PREFIX = "zjrt_"
STORED_PREFIX_LENGTH = 20


def extract_runtime_credential(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token.startswith(RUNTIME_CREDENTIAL_PREFIX):
            return token
    raise HTTPException(status_code=401, detail="Missing or invalid ECS runtime credential")


async def authenticate_ecs_runtime(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EcsRuntime:
    raw = extract_runtime_credential(request)
    if len(raw) < 40 or len(raw) > 256:
        raise HTTPException(status_code=401, detail="Invalid ECS runtime credential")
    row = (
        await db.execute(
            select(EcsRuntime).where(
                EcsRuntime.credential_prefix == raw[:STORED_PREFIX_LENGTH],
                EcsRuntime.credential_hash == hash_api_key(raw),
                EcsRuntime.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked ECS runtime credential")
    row.last_seen_at = datetime.now(UTC)
    await db.flush()
    return row
