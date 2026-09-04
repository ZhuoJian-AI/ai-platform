"""WebOffice editing sessions and durable OSS-version reconciliation."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_auth import current_user_for_user
from app.config import settings
from app.models.admin import Admin
from app.models.user import User
from app.models.workspace import (
    OfficeEditRoom,
    OfficeSaveEvent,
    WorkspaceFile,
    WorkspaceFileVersion,
)
from app.services import storage_gateway_service, workspace_permission_service, workspace_service
from app.services.workspace_preview_service import OriginalPreviewError, source_metadata

# Active write-conflict protection is a renewable lease, not the callback
# provenance retention window. A crashed browser must not block Agent/human
# updates for an entire day.
ACTIVE_ROOM_LEASE_SECONDS = 35 * 60
CALLBACK_RETENTION_SECONDS = 24 * 60 * 60
_token_cache: dict[str, tuple[float, dict]] = {}


def _numeric_imm_version(value: str | None) -> int | None:
    """Parse IMM's monotonic document version only when it is unambiguous."""
    raw = str(value or "").strip()
    return int(raw) if raw.isdecimal() else None


def _event_timestamp(value: str | None) -> datetime | None:
    """Parse standard callback timestamps without inventing an ordering."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        # Some notification transports serialize Unix seconds/milliseconds.
        if raw.isdecimal():
            stamp = int(raw)
            if stamp > 10_000_000_000:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, tz=UTC)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _save_event_order(candidate: OfficeSaveEvent, previous: OfficeSaveEvent) -> int | None:
    """Return candidate ordering against one applied event.

    Numeric IMM versions are authoritative when both sides expose them.  A
    timestamp is only used when an IMM version cannot be compared on both
    sides.  ``None`` deliberately means "cannot prove this event is newer";
    reconciliation must not guess and risk rolling the logical file back.
    """
    candidate_version = _numeric_imm_version(candidate.imm_version)
    previous_version = _numeric_imm_version(previous.imm_version)
    if candidate_version is not None and previous_version is not None:
        return (candidate_version > previous_version) - (candidate_version < previous_version)
    candidate_time = _event_timestamp(candidate.event_time)
    previous_time = _event_timestamp(previous.event_time)
    if candidate_time is not None and previous_time is not None:
        return (candidate_time > previous_time) - (candidate_time < previous_time)
    return None


def weboffice_user_id(actor_type: str, actor_id: str) -> str:
    return hashlib.sha256(f"{actor_type}:{actor_id}".encode()).hexdigest()[:15]


def _validate_editable(file: WorkspaceFile) -> tuple[str, str]:
    if not settings.workspace_weboffice_edit_configured:
        raise OriginalPreviewError("在线 Office 编辑尚未启用")
    if not storage_gateway_service.is_object_ref(file.content_ref):
        raise OriginalPreviewError("该历史文件尚未迁移到对象存储，不能在线编辑")
    filename, mime_type = source_metadata(file)
    if PurePosixPath(filename).suffix.lower() not in workspace_service.WEBOFFICE_EDITABLE_SUFFIXES:
        raise OriginalPreviewError("该文件格式不支持在线编辑")
    if int(file.size or 0) > settings.workspace_weboffice_max_bytes:
        raise OriginalPreviewError("文件超过 200MB 在线编辑上限")
    if not file.current_version_id:
        raise OriginalPreviewError("文件当前版本尚未就绪")
    return filename, mime_type


async def create_edit_session(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    actor_type: str,
    actor_id: str,
    client_open_id: str,
) -> dict:
    # Serialize room creation against Agent/human mutations.  Those writers
    # take the same logical-file row lock before checking active rooms, closing
    # the race where both an edit room and an out-of-band overwrite could win.
    locked_file = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id == file.id,
        WorkspaceFile.deleted_at.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if locked_file is None:
        raise OriginalPreviewError("文件已删除或不可编辑")
    file = locked_file
    filename, mime_type = _validate_editable(file)
    now = datetime.now(UTC)
    room = (await db.execute(
        select(OfficeEditRoom).where(
            OfficeEditRoom.workspace_file_id == file.id,
            OfficeEditRoom.actor_type == actor_type,
            OfficeEditRoom.actor_id == actor_id,
            OfficeEditRoom.client_open_id == client_open_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if room is not None and not (
        room.status == "open" and room.expires_at > now
    ):
        raise OriginalPreviewError("该编辑窗口已结束，请重新打开文件")
    anchor = room
    if anchor is None:
        anchor = (await db.execute(select(OfficeEditRoom).where(
            OfficeEditRoom.workspace_file_id == file.id,
            OfficeEditRoom.status == "open",
            OfficeEditRoom.expires_at > now,
        ).order_by(OfficeEditRoom.created_at.asc()).limit(1))).scalar_one_or_none()
    source_content_ref = str(anchor.source_content_ref if anchor is not None else file.content_ref)
    source_file_version_id = anchor.source_file_version_id if anchor is not None else file.current_version_id
    if room is None:
        # Gateway binds the immutable room UUID into IMM UserData.  Persist it
        # before requesting a token so delayed callbacks can never be matched
        # heuristically to a newer room.
        room = OfficeEditRoom(
            workspace_file_id=file.id,
            source_file_version_id=source_file_version_id,
            source_content_ref=source_content_ref,
            source_storage_version_id=(
                anchor.source_storage_version_id if anchor is not None else None
            ),
            source_revision=anchor.source_revision if anchor is not None else None,
            source_etag=anchor.source_etag if anchor is not None else None,
            actor_type=actor_type,
            actor_id=actor_id,
            client_open_id=client_open_id,
            status="open",
            expires_at=now + timedelta(seconds=ACTIVE_ROOM_LEASE_SECONDS),
        )
        db.add(room)
        await db.flush()
    else:
        room.expires_at = now + timedelta(seconds=ACTIVE_ROOM_LEASE_SECONDS)
        room.last_error = None
        await db.flush()
    cache_key = f"{room.id}:{source_file_version_id}"
    cached = _token_cache.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return dict(cached[1])

    user_id = weboffice_user_id(actor_type, actor_id)
    try:
        token = await storage_gateway_service.generate_weboffice_token(
            source_content_ref,
            filename=filename,
            user_id=user_id,
            file_id=str(file.id),
            room_id=str(room.id),
            mode="edit",
        )
    except storage_gateway_service.StorageGatewayError:
        room.status = "failed"
        room.last_error = "WebOffice 编辑会话创建失败"
        await db.flush()
        raise
    source_storage_version_id = str(token.get("source_version_id") or "") or None
    source_revision = str(token.get("source_revision") or "").lower()
    if len(source_revision) != 64 or any(
        character not in "0123456789abcdef" for character in source_revision
    ):
        room.status = "failed"
        room.last_error = "协同存储来源校验信息缺失"
        await db.flush()
        raise OriginalPreviewError("对象存储来源校验失败，已拒绝创建编辑会话")
    room.source_storage_version_id = source_storage_version_id
    room.source_revision = source_revision
    await db.flush()
    result = {
        "mode": "edit",
        "filename": filename,
        "mime_type": mime_type,
        "size": int(file.size or 0),
        "room_id": str(room.id),
        "save_status": room.status,
        **token,
    }
    _token_cache[cache_key] = (time.monotonic() + 10 * 60, result)
    if len(_token_cache) > 512:
        now = time.monotonic()
        for key in [key for key, value in _token_cache.items() if value[0] <= now]:
            _token_cache.pop(key, None)
    return dict(result)


async def refresh_edit_session(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    actor_type: str,
    actor_id: str,
    access_token: str,
    refresh_token: str,
    refresh_context: str,
    room_id: UUID,
) -> dict:
    filename, mime_type = _validate_editable(file)
    room = (await db.execute(select(OfficeEditRoom).where(
        OfficeEditRoom.id == room_id,
        OfficeEditRoom.workspace_file_id == file.id,
        OfficeEditRoom.actor_type == actor_type,
        OfficeEditRoom.actor_id == actor_id,
        OfficeEditRoom.status == "open",
        OfficeEditRoom.expires_at > datetime.now(UTC),
    ).with_for_update())).scalar_one_or_none()
    if room is None:
        raise OriginalPreviewError("在线编辑会话已关闭，请重新进入编辑")
    token = await storage_gateway_service.refresh_weboffice_token(
        str(room.source_content_ref),
        access_token=access_token,
        refresh_token=refresh_token,
        refresh_context=refresh_context,
        user_id=weboffice_user_id(actor_type, actor_id),
        file_id=str(file.id),
        room_id=str(room.id),
        mode="edit",
    )
    refreshed_revision = str(token.get("source_revision") or "").lower()
    if not room.source_revision or refreshed_revision != room.source_revision:
        room.status = "failed"
        room.last_error = "编辑会话来源校验失败"
        await db.flush()
        raise OriginalPreviewError("编辑会话来源已变化，请重新打开文件")
    room.expires_at = datetime.now(UTC) + timedelta(seconds=ACTIVE_ROOM_LEASE_SECONDS)
    room.last_error = None
    await db.flush()
    return {
        "mode": "edit",
        "filename": filename,
        "mime_type": mime_type,
        "size": int(file.size or 0),
        "room_id": str(room.id),
        "save_status": room.status,
        **token,
    }


async def close_edit_session(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    actor_type: str,
    actor_id: str,
    client_open_id: str,
) -> OfficeEditRoom | None:
    room = (await db.execute(select(OfficeEditRoom).where(
        OfficeEditRoom.workspace_file_id == file.id,
        OfficeEditRoom.actor_type == actor_type,
        OfficeEditRoom.actor_id == actor_id,
        OfficeEditRoom.client_open_id == client_open_id,
    ).with_for_update())).scalar_one_or_none()
    if room is None:
        return None
    if room.status in {"open", "closing"}:
        room.status = "closing"
        now = datetime.now(UTC)
        room.closed_at = now
        # A close request is not proof that IMM has persisted the last keystroke.
        # Keep a short conflict-protection grace period for an in-flight MNS
        # SaveVersion event.  The event, not this request, closes reconciliation.
        room.expires_at = min(room.expires_at, now + timedelta(minutes=5))
    await db.flush()
    return room


async def active_room(db: AsyncSession, file_id: UUID | str) -> OfficeEditRoom | None:
    now = datetime.now(UTC)
    return (await db.execute(select(OfficeEditRoom).where(
        OfficeEditRoom.workspace_file_id == file_id,
        OfficeEditRoom.status.in_(("open", "closing")),
        OfficeEditRoom.expires_at > now,
    ).order_by(OfficeEditRoom.created_at.desc()).limit(1))).scalar_one_or_none()


async def get_edit_room(
    db: AsyncSession,
    file: WorkspaceFile,
    *,
    room_id: UUID,
    actor_type: str,
    actor_id: str,
) -> OfficeEditRoom | None:
    """Return only the caller's exact room for this logical file."""
    return (await db.execute(select(OfficeEditRoom).where(
        OfficeEditRoom.id == room_id,
        OfficeEditRoom.workspace_file_id == file.id,
        OfficeEditRoom.actor_type == actor_type,
        OfficeEditRoom.actor_id == actor_id,
    ))).scalar_one_or_none()


async def _actor_can_still_update(
    db: AsyncSession,
    room: OfficeEditRoom,
    file: WorkspaceFile,
) -> bool:
    """Revalidate the human principal immediately before materialization."""
    workspace = await workspace_service.get_workspace(db, file.workspace_id)
    if workspace is None:
        return False
    if room.actor_type == "user":
        try:
            user_id = UUID(str(room.actor_id))
        except (TypeError, ValueError):
            return False
        user = await db.get(User, user_id)
        if (
            user is None
            or not user.is_active
            or user.deleted_at is not None
            or str(user.organization_id) != str(workspace.organization_id)
        ):
            return False
        principal = await current_user_for_user(db, user)
        return bool((await workspace_permission_service.capabilities(
            db, workspace, principal,
        )).get("update"))
    if room.actor_type == "admin":
        try:
            admin_id = int(room.actor_id)
        except (TypeError, ValueError):
            return False
        admin = await db.get(Admin, admin_id)
        return bool(
            admin is not None
            and admin.is_active
            and (
                admin.organization_id is None
                or str(admin.organization_id) == str(workspace.organization_id)
            )
        )
    return False


async def edit_room_status_payload(
    db: AsyncSession,
    file: WorkspaceFile,
    room: OfficeEditRoom,
) -> dict:
    """Expose deterministic reconciliation state without leaking credentials."""
    latest = (await db.execute(select(OfficeSaveEvent).where(
        OfficeSaveEvent.office_edit_room_id == room.id,
    ).order_by(OfficeSaveEvent.created_at.desc()).limit(1))).scalar_one_or_none()
    now = datetime.now(UTC)
    terminal_failure = latest is not None and latest.status in {"failed", "conflict"}
    has_reconciled_save = bool(
        room.final_file_version_id
        or (latest is not None and latest.status in {"completed", "coalesced"})
    )
    if room.status == "failed" or terminal_failure:
        status = "failed"
    elif room.status == "closed":
        status = "reconciled" if has_reconciled_save else "expired"
    elif room.expires_at <= now:
        status = "reconciled" if has_reconciled_save else "expired"
    else:
        status = room.status if room.status in {"open", "closing"} else "failed"

    if terminal_failure or room.status == "failed":
        save_status = "failed"
    elif latest is not None and latest.status in {"queued", "processing"}:
        save_status = "reconciling"
    elif has_reconciled_save:
        save_status = "reconciled"
    elif status == "expired":
        save_status = "expired"
    else:
        save_status = "waiting"
    error = None
    if save_status == "failed":
        error = str((latest.error if latest is not None else None) or room.last_error or "保存对账失败")[:500]
    return {
        "room_id": room.id,
        "status": status,
        "save_status": save_status,
        "source_file_version_id": room.source_file_version_id,
        "final_file_version_id": room.final_file_version_id,
        "current_version_id": file.current_version_id,
        "error": error,
    }


async def record_save_event(db: AsyncSession, event: dict) -> OfficeSaveEvent:
    event_id = str(event["event_id"])
    existing = (await db.execute(select(OfficeSaveEvent).where(
        OfficeSaveEvent.gateway_event_id == event_id,
    ))).scalar_one_or_none()
    if existing is not None:
        return existing
    try:
        file_id = UUID(str(event["file_id"]))
        room_id = UUID(str(event["room_id"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid file or room id") from exc
    file = await workspace_service.get_file(db, file_id)
    if file is None:
        raise ValueError("file is unavailable")
    repository_id = str(event["repository_id"])
    source_object_key = str(event["source_object_key"])
    object_key = str(event["object_key"])
    project_prefix = f"projects/{repository_id}/"
    if not source_object_key.startswith(project_prefix) or not object_key.startswith(project_prefix):
        raise ValueError("save event is outside the project prefix")
    user_id = str(event["user_id"])
    source_revision = str(event.get("source_revision") or "").lower()
    integrity_algorithm = str(event.get("integrity_algorithm") or "").lower()
    integrity_value = str(event.get("integrity_value") or "")
    if (
        len(source_revision) != 64
        or any(character not in "0123456789abcdef" for character in source_revision)
        or integrity_algorithm != "crc64ecma"
        or not integrity_value.isdecimal()
    ):
        raise ValueError("invalid save event integrity provenance")
    now = datetime.now(UTC)
    callback_retention_floor = now - timedelta(seconds=CALLBACK_RETENTION_SECONDS)
    room = await db.get(OfficeEditRoom, room_id)
    room_is_active = bool(
        room is not None
        and getattr(room, "status", None) in {"open", "closing"}
        and getattr(room, "expires_at", now) > now
    )
    retention_anchor = (
        (getattr(room, "closed_at", None) or getattr(room, "expires_at", None))
        or getattr(room, "created_at", None)
        if room is not None else None
    )
    room_is_retained = bool(
        room is not None
        and not room_is_active
        and retention_anchor is not None
        and retention_anchor >= callback_retention_floor
    )
    if not (
        room is not None
        and str(room.workspace_file_id) == str(file.id)
        and (room_is_active or room_is_retained)
        and storage_gateway_service.object_key_from_ref(str(room.source_content_ref))
        == source_object_key
        and weboffice_user_id(room.actor_type, room.actor_id) == user_id
        and room.source_revision == source_revision
    ):
        raise ValueError("save event has no matching authorized edit room")
    row = OfficeSaveEvent(
        gateway_event_id=event_id,
        workspace_file_id=file.id,
        office_edit_room_id=room.id,
        repository_id=repository_id,
        source_object_key=source_object_key,
        object_key=object_key,
        notified_storage_version_id=str(event.get("version_id") or "") or None,
        notified_etag=str(event["etag"]).strip('"'),
        notified_size=int(event["size"]),
        notified_content_type=str(event["content_type"]),
        notified_content_hash=str(event["content_hash"]),
        source_user_id=user_id,
        source_revision=source_revision,
        notified_integrity_algorithm=integrity_algorithm,
        notified_integrity_value=integrity_value,
        imm_version=str(event.get("imm_version") or "") or None,
        event_time=str(event.get("event_time") or "") or None,
        status="queued",
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # Two deliveries of the same authenticated MNS notification may race.
        # The unique gateway_event_id is authoritative; contain the loser in a
        # savepoint so the callback transaction remains usable and return the
        # already-recorded durable receipt.
        existing = (await db.execute(select(OfficeSaveEvent).where(
            OfficeSaveEvent.gateway_event_id == event_id,
        ))).scalar_one_or_none()
        if existing is None:
            raise ValueError("save event idempotency race; retry") from None
        return existing
    return row


async def claim_save_event(db: AsyncSession, *, worker_id: str) -> OfficeSaveEvent | None:
    now = datetime.now(UTC)
    row = (await db.execute(select(OfficeSaveEvent).where(
        OfficeSaveEvent.next_attempt_at <= now,
        OfficeSaveEvent.attempt_count < 12,
        or_(
            OfficeSaveEvent.status == "queued",
            (OfficeSaveEvent.status == "processing") & (OfficeSaveEvent.lease_expires_at < now),
        ),
    ).order_by(OfficeSaveEvent.next_attempt_at, OfficeSaveEvent.created_at)
      .with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
    if row is None:
        return None
    row.status = "processing"
    row.attempt_count = int(row.attempt_count or 0) + 1
    row.locked_by = worker_id
    row.lease_expires_at = now + timedelta(seconds=settings.workspace_office_reconcile_lease_seconds)
    row.error = None
    await db.flush()
    return row


async def reconcile_save_event(db: AsyncSession, event: OfficeSaveEvent) -> str:
    file = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id == event.workspace_file_id,
        WorkspaceFile.deleted_at.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if file is None:
        event.status = "ignored"
        event.error = "file unavailable"
        return "ignored"
    room = await db.get(OfficeEditRoom, event.office_edit_room_id) if event.office_edit_room_id else None
    if (
        room is None
        or str(room.workspace_file_id) != str(file.id)
        or storage_gateway_service.object_key_from_ref(str(room.source_content_ref))
        != event.source_object_key
        or weboffice_user_id(room.actor_type, room.actor_id) != event.source_user_id
        or not room.source_revision
        or room.source_revision != event.source_revision
    ):
        event.status = "conflict"
        event.error = "edit room source no longer matches"
        return "conflict"
    if not await _actor_can_still_update(db, room, file):
        now = datetime.now(UTC)
        event.status = "conflict"
        event.error = "edit permission revoked before save"
        event.lease_expires_at = None
        room.status = "failed"
        room.closed_at = room.closed_at or now
        room.expires_at = now
        room.last_error = "文件编辑权限已撤销，保存已拒绝"
        return "conflict"
    project_prefix = f"projects/{event.repository_id}/"
    if not event.object_key.startswith(project_prefix):
        event.status = "conflict"
        event.error = "saved object is outside the project prefix"
        return "conflict"
    saved_ref = f"{storage_gateway_service.OSS_REF_PREFIX}{event.object_key}"
    resolved = await storage_gateway_service.resolve_weboffice_version(
        saved_ref,
        file_id=str(file.id),
        version_id=event.notified_storage_version_id,
    )
    storage_version_id = str(resolved.get("version_id") or "") or None
    event.resolved_storage_version_id = storage_version_id
    resolved_etag = str(resolved.get("etag") or "").strip('"')
    resolved_size = int(resolved.get("size_bytes") or resolved.get("size") or 0)
    resolved_integrity_algorithm = str(resolved.get("integrity_algorithm") or "").lower()
    resolved_integrity_value = str(resolved.get("integrity_value") or "")
    if (
        (
            event.notified_storage_version_id is not None
            and storage_version_id != event.notified_storage_version_id
        )
        or not resolved_etag
        or resolved_etag != event.notified_etag.strip('"')
        or resolved_size != int(event.notified_size)
        or str(resolved.get("content_type") or "") != event.notified_content_type
        or str(resolved.get("content_hash") or "") != event.notified_content_hash
        or resolved_integrity_algorithm != event.notified_integrity_algorithm
        or resolved_integrity_value != event.notified_integrity_value
    ):
        event.status = "conflict"
        event.error = "saved object verification mismatch"
        return "conflict"
    # File-row locking above serializes callbacks for this logical file.  Only
    # an event provably newer than every previously applied event from the same
    # collaborative source may become current.  MNS redelivery and cross-
    # worker scheduling can otherwise apply version 11 and later roll back to
    # delayed version 10.
    applied_events = list((await db.execute(select(OfficeSaveEvent).where(
        OfficeSaveEvent.id != event.id,
        OfficeSaveEvent.workspace_file_id == file.id,
        OfficeSaveEvent.source_object_key == event.source_object_key,
        OfficeSaveEvent.status == "completed",
        OfficeSaveEvent.resolved_file_version_id.is_not(None),
    ).order_by(OfficeSaveEvent.created_at.desc()))).scalars())
    for applied in applied_events:
        ordering = _save_event_order(event, applied)
        if ordering is None:
            event.status = "conflict"
            event.error = "save event ordering is not comparable"
            event.lease_expires_at = None
            return "conflict"
        if ordering <= 0:
            event.status = "superseded"
            event.error = "save event is older than an applied version"
            event.lease_expires_at = None
            return "superseded"

    # After the room's short active grace period an Agent or human API may have
    # committed a different lineage.  A delayed Office callback may advance
    # only its original source revision (or a version already reconciled from
    # that same source), never overwrite an unrelated newer edit.
    allowed_current_versions = {str(room.source_file_version_id)}
    allowed_current_versions.update(
        str(applied.resolved_file_version_id)
        for applied in applied_events
        if applied.resolved_file_version_id is not None
    )
    if str(file.current_version_id or "") not in allowed_current_versions:
        event.status = "conflict"
        event.error = "logical file advanced outside this edit source"
        event.lease_expires_at = None
        return "conflict"

    # Coalescing is safe only after both callback ordering *and* current-file
    # lineage checks.  Otherwise a delayed callback whose object was already
    # materialized could report success and move the room's final pointer even
    # after an unrelated Agent/human update advanced the logical file.
    # Materialized business object keys are unique per Gateway event, so the
    # content reference remains immutable even when that bucket is unversioned.
    existing = (await db.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == file.id,
        WorkspaceFileVersion.content_ref == saved_ref,
    ).limit(1))).scalar_one_or_none()
    if existing is not None:
        event.status = "coalesced"
        event.resolved_file_version_id = existing.id
        room.final_file_version_id = existing.id
        if room.status == "closing":
            room.status = "closed"
            room.reconciled_at = datetime.now(UTC)
        event.lease_expires_at = None
        return "coalesced"

    metadata = {
        **(file.metadata_ or {}),
        "storage_version_id": storage_version_id,
        "etag": resolved_etag,
        "integrity_algorithm": resolved_integrity_algorithm,
        "integrity_value": resolved_integrity_value,
        "mime": str(resolved.get("content_type") or (file.metadata_ or {}).get("mime") or "application/octet-stream"),
    }
    file.content_ref = saved_ref
    file.metadata_ = metadata
    file.size = resolved_size
    file.content_hash = event.notified_content_hash
    file.content = None
    file.extracted_text = None
    file.parse_status = "queued"
    file.parse_kind = None
    file.parse_error = None
    version = await workspace_service.create_file_version(db, file)
    version.storage_version_id = storage_version_id
    version.storage_etag = str(resolved.get("etag") or "") or None
    event.status = "completed"
    event.resolved_file_version_id = version.id
    event.lease_expires_at = None
    room.final_file_version_id = version.id
    if room.status == "closing":
        room.status = "closed"
        room.reconciled_at = datetime.now(UTC)
    await db.flush()
    return "completed"


def retry_save_event(event: OfficeSaveEvent, reason: str) -> None:
    event.error = reason[:500]
    event.lease_expires_at = None
    if event.attempt_count >= 12:
        event.status = "failed"
        return
    event.status = "queued"
    delay = min(60, 2 ** min(int(event.attempt_count or 1), 5))
    event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
