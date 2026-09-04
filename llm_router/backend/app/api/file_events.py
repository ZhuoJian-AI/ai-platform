"""Role-filtered workspace file version events for the terminal client."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.auth.user_auth import CurrentUser, current_user_for_user, require_user
from app.database import async_session_factory
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceFileEventOutbox
from app.services import workspace_permission_service

router = APIRouter(prefix="/terminal/file-events")


def _event_payload(row: WorkspaceFileEventOutbox) -> str:
    return json.dumps(
        {
            "id": int(row.id),
            "workspace_id": str(row.workspace_id),
            "file_id": str(row.workspace_file_id),
            "version_id": str(row.version_id) if row.version_id else None,
            "event_type": row.event_type,
            "created_at": row.created_at.isoformat(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


@router.get("/stream")
async def stream_file_events(
    request: Request,
    after: int = Query(0, ge=0),
    cu: CurrentUser = Depends(require_user),
) -> StreamingResponse:
    """Stream only events whose workspace remains readable by this user.

    Authorization is recalculated for every batch, so role revocation takes
    effect without reconnecting.  Event bodies contain identifiers only.
    """

    # Resolve a fresh connection's baseline before creating the stream and
    # immediately disclose it to the client.  If the connection drops before
    # a business event, the reconnect can now resume from this exact cursor
    # instead of recomputing max(id) and skipping the disconnect window.
    baseline = int(after)
    if baseline == 0:
        async with async_session_factory() as db:
            baseline = int((await db.scalar(
                select(func.coalesce(func.max(WorkspaceFileEventOutbox.id), 0)).where(
                    WorkspaceFileEventOutbox.organization_id == cu.organization_id,
                )
            )) or 0)

    async def events():
        cursor = baseline
        emitted_cursor = baseline
        yield (
            f"retry: 1500\nid: {cursor}\nevent: cursor\n"
            f"data: {json.dumps({'cursor': cursor}, separators=(',', ':'))}\n\n"
        )
        idle_ticks = 0
        while not await request.is_disconnected():
            delivered = False
            async with async_session_factory() as db:
                live_user = (await db.execute(select(User).where(
                    User.id == UUID(str(cu.id)),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                ))).scalar_one_or_none()
                if live_user is None:
                    return
                live_principal = await current_user_for_user(db, live_user)
                rows = list((await db.execute(
                    select(WorkspaceFileEventOutbox)
                    .where(
                        WorkspaceFileEventOutbox.organization_id == cu.organization_id,
                        WorkspaceFileEventOutbox.id > cursor,
                    )
                    .order_by(WorkspaceFileEventOutbox.id)
                    .limit(100)
                )).scalars())
                workspace_cache: dict[str, bool] = {}
                for row in rows:
                    cursor = max(cursor, int(row.id))
                    key = str(row.workspace_id)
                    allowed = workspace_cache.get(key)
                    if allowed is None:
                        workspace = await db.get(Workspace, row.workspace_id)
                        allowed = bool(
                            workspace is not None
                            and (
                                await workspace_permission_service.capabilities(
                                    db, workspace, live_principal,
                                )
                            )["read"]
                        )
                        workspace_cache[key] = allowed
                    if not allowed:
                        continue
                    delivered = True
                    emitted_cursor = int(row.id)
                    yield f"id: {row.id}\nevent: workspace-file\ndata: {_event_payload(row)}\n\n"
                if cursor > emitted_cursor:
                    emitted_cursor = cursor
                    yield (
                        f"id: {cursor}\nevent: cursor\n"
                        f"data: {json.dumps({'cursor': cursor}, separators=(',', ':'))}\n\n"
                    )
            if delivered:
                idle_ticks = 0
                continue
            idle_ticks += 1
            if idle_ticks >= 15:
                yield ": keep-alive\n\n"
                idle_ticks = 0
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
