"""Private, authenticated receipts for Storage Gateway WebOffice save events."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import workspace_office_edit_service

router = APIRouter(prefix="/internal/weboffice")


class OfficeSaveEventReceipt(BaseModel):
    """Minimal event forwarded by the trusted Storage Gateway.

    The payload intentionally contains no file body, OSS credential, signed URL,
    WebOffice token, or raw IMM userData.
    """

    event_id: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    file_id: str = Field(..., min_length=36, max_length=36)
    room_id: str = Field(..., min_length=36, max_length=36)
    repository_id: str = Field(..., min_length=1, max_length=128)
    source_object_key: str = Field(..., min_length=1, max_length=2048)
    object_key: str = Field(..., min_length=1, max_length=2048)
    version_id: str | None = Field(None, max_length=1024)
    etag: str = Field(..., min_length=1, max_length=256)
    size: int = Field(..., gt=0)
    content_type: str = Field(..., min_length=1, max_length=255)
    content_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    user_id: str = Field(..., min_length=1, max_length=64)
    source_revision: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    integrity_algorithm: str = Field(..., pattern=r"^crc64ecma$")
    integrity_value: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9]+$")
    imm_version: str = Field("", max_length=128)
    event_time: str = Field("", max_length=128)


def _verify_gateway_signature(raw_body: bytes, timestamp: str | None, signature: str | None) -> None:
    secret = settings.workspace_office_event_callback_secret_value
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="office save callback is not configured")
    if timestamp is None or signature is None:
        raise HTTPException(status_code=401, detail="invalid office save callback signature")
    try:
        issued_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid office save callback signature") from exc
    if abs(int(time.time()) - issued_at) > 300:
        raise HTTPException(status_code=401, detail="expired office save callback signature")
    expected = hmac.new(
        secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw_body, hashlib.sha256,
    ).hexdigest()
    supplied = signature.removeprefix("sha256=")
    if len(supplied) != len(expected) or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid office save callback signature")


@router.post("/save-events", status_code=202)
async def receive_save_event(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_office_event_timestamp: Annotated[str | None, Header()] = None,
    x_office_event_signature: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > 16 * 1024:
                raise HTTPException(status_code=413, detail="office save event is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content length") from exc
    raw_body = await request.body()
    if len(raw_body) > 16 * 1024:
        raise HTTPException(status_code=413, detail="office save event is too large")
    _verify_gateway_signature(raw_body, x_office_event_timestamp, x_office_event_signature)
    try:
        event = OfficeSaveEventReceipt.model_validate_json(raw_body)
        row = await workspace_office_edit_service.record_save_event(db, event.model_dump())
    except (ValueError, TypeError) as exc:
        # The public detail stays generic so a forged callback cannot probe file
        # ids, object keys, tenant membership, or edit-room state.
        raise HTTPException(status_code=400, detail="invalid office save event") from exc
    response.headers["Cache-Control"] = "no-store"
    return {"status": "accepted", "event_id": str(row.gateway_event_id)}
