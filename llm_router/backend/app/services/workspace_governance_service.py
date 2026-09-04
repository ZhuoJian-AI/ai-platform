"""Upload sessions, immutable versions, publishing, trash and audit."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin
from app.auth.user_auth import CurrentUser, current_user_for_user
from app.config import settings
from app.models.admin import Admin
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceAuditEvent,
    WorkspaceFile,
    WorkspaceFileVersion,
    WorkspacePreviewJob,
    WorkspaceShareLink,
    WorkspaceUploadSession,
)
from app.schemas.workspace import WorkspaceFileCreate, WorkspaceUploadInitiate
from app.services import storage_gateway_service, workspace_permission_service, workspace_service
from app.services.storage_lifecycle_service import restore
from app.utils.workspace_presentation import presentation_dict


def _validate_direct_upload_size(size: int) -> None:
    """Validate a browser-to-object-storage upload.

    The proxy/direct threshold is a client-side routing preference, not a
    protocol constraint. Accepting small direct uploads keeps clients working
    when their configured thresholds differ from the server.
    """
    if size > settings.workspace_max_file_bytes:
        raise HTTPException(status_code=413, detail="文件超过 5GB 上传上限")


async def _resolve_upload_target(
    db: AsyncSession,
    ws: Workspace,
    data: WorkspaceUploadInitiate,
) -> WorkspaceFile | None:
    """Validate create-only vs explicit optimistic version upload semantics."""
    path = workspace_service._normalize_path(data.path)
    existing = await workspace_service.get_file_by_path(db, ws.id, path)
    if data.target_file_id is None:
        if existing is not None:
            raise HTTPException(status_code=409, detail={
                "code": "workspace_file_path_conflict",
                "message": "目标路径已存在；请明确选择作为该文件的新版本上传",
                "file_id": str(existing.id),
                "current_version_id": (
                    str(existing.current_version_id) if existing.current_version_id else None
                ),
            })
        return None
    target = await workspace_service.get_file(db, data.target_file_id)
    if (
        target is None
        or str(target.workspace_id) != str(ws.id)
        or target.path != path
        or existing is None
        or str(existing.id) != str(target.id)
    ):
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_replacement_target_mismatch",
            "message": "目标文件与当前工作空间路径不匹配，请刷新文件列表后重试",
        })
    if str(target.current_version_id or "") != str(data.base_version_id or ""):
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_version_conflict",
            "message": "文件已被其他人更新，请刷新后重试",
            "current_version_id": (
                str(target.current_version_id) if target.current_version_id else None
            ),
        })
    try:
        await workspace_service.assert_no_active_office_room(db, target)
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict",
            "message": str(exc),
            "room_id": exc.room_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    return target


async def audit(
    db: AsyncSession,
    ws: Workspace,
    action: str,
    *,
    user_id: str | UUID | None = None,
    admin_id: int | None = None,
    file: WorkspaceFile | None = None,
    version_id: str | UUID | None = None,
    metadata: dict | None = None,
) -> None:
    audit_metadata = dict(metadata or {})
    if file is not None:
        presentation = presentation_dict(file.path, file.metadata_ or {}, created_at=file.created_at)
        audit_metadata.setdefault("display_name", presentation["display_name"])
        audit_metadata.setdefault("path", file.path)
    db.add(WorkspaceAuditEvent(
        organization_id=ws.organization_id,
        workspace_id=ws.id,
        workspace_file_id=file.id if file else None,
        version_id=version_id,
        actor_user_id=user_id,
        actor_admin_id=admin_id,
        action=action,
        metadata_=audit_metadata,
    ))
    await db.flush()


def transient_upload_authorization(session: WorkspaceUploadSession) -> dict:
    """Return one initiate-response credential bundle kept only in memory.

    Signed OSS URLs and request headers are bearer credentials.  Pending
    upload sessions need durable routing/idempotency state, but must never
    persist those credentials in PostgreSQL or audit metadata.
    """
    value = getattr(session, "_transient_upload_authorization", None)
    return dict(value) if isinstance(value, dict) else {}


def _attach_transient_upload_authorization(
    session: WorkspaceUploadSession,
    signed: dict,
) -> None:
    setattr(session, "_transient_upload_authorization", {
        "url": signed.get("url"),
        "fallback_url": signed.get("fallback_url"),
        "headers": dict(signed.get("headers") or {}),
    })


async def initiate_direct_upload(
    db: AsyncSession, ws: Workspace, cu: CurrentUser, data: WorkspaceUploadInitiate,
) -> WorkspaceUploadSession:
    if not settings.workspace_hybrid_upload_enabled:
        raise HTTPException(status_code=503, detail="新版上传链路已由部署级开关暂时关闭")
    if not settings.workspace_object_storage_configured:
        raise HTTPException(status_code=503, detail="大文件上传要求已配置对象存储")
    _validate_direct_upload_size(data.size)
    path = workspace_service._normalize_path(data.path)
    if not path:
        raise HTTPException(status_code=422, detail="文件路径不能为空")
    target = await _resolve_upload_target(db, ws, data)
    if target is None:
        await workspace_permission_service.assert_can_create(db, ws, cu)
    else:
        await workspace_permission_service.assert_can_update(db, ws, cu)
    try:
        signed = await storage_gateway_service.sign_browser_upload(
            filename=data.filename, content_type=data.content_type, size_bytes=data.size,
            weak_network=data.weak_network,
        )
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    upload_meta = {
        "transport": str(signed.get("method") or "PUT").lower(),
        "gateway_session_id": signed.get("gateway_session_id"),
        "part_size": signed.get("part_size"),
        "expected_parts": signed.get("expected_parts"),
        "target_file_id": str(data.target_file_id) if data.target_file_id else None,
        "base_version_id": str(data.base_version_id) if data.base_version_id else None,
        "idempotency_key": data.idempotency_key,
    }
    session = WorkspaceUploadSession(
        organization_id=cu.organization_id,
        workspace_id=ws.id,
        user_id=UUID(cu.id),
        path=path,
        original_filename=data.filename,
        content_type=data.content_type,
        expected_size=data.size,
        content_ref=f"oss://{signed['object_key']}",
        upload_url=None,
        upload_headers=upload_meta,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.workspace_upload_session_ttl_seconds),
    )
    db.add(session)
    await db.flush()
    _attach_transient_upload_authorization(session, signed)
    await audit(db, ws, "upload_initiated", user_id=cu.id, metadata={"size": data.size, "path": path})
    return session


async def initiate_admin_direct_upload(
    db: AsyncSession, ws: Workspace, auth: CurrentAdmin, data: WorkspaceUploadInitiate,
) -> WorkspaceUploadSession:
    if not settings.workspace_hybrid_upload_enabled:
        raise HTTPException(status_code=503, detail="新版上传链路已由部署级开关暂时关闭")
    if not settings.workspace_object_storage_configured:
        raise HTTPException(status_code=503, detail="大文件上传要求已配置对象存储")
    _validate_direct_upload_size(data.size)
    path = workspace_service._normalize_path(data.path)
    if not path:
        raise HTTPException(status_code=422, detail="文件路径不能为空")
    await _resolve_upload_target(db, ws, data)
    try:
        signed = await storage_gateway_service.sign_browser_upload(
            filename=data.filename, content_type=data.content_type, size_bytes=data.size,
            weak_network=data.weak_network,
        )
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    upload_meta = {
        "transport": str(signed.get("method") or "PUT").lower(),
        "gateway_session_id": signed.get("gateway_session_id"),
        "part_size": signed.get("part_size"),
        "expected_parts": signed.get("expected_parts"),
        "target_file_id": str(data.target_file_id) if data.target_file_id else None,
        "base_version_id": str(data.base_version_id) if data.base_version_id else None,
        "idempotency_key": data.idempotency_key,
    }
    session = WorkspaceUploadSession(
        organization_id=ws.organization_id,
        workspace_id=ws.id,
        user_id=None,
        admin_id=auth.id,
        path=path,
        original_filename=data.filename,
        content_type=data.content_type,
        expected_size=data.size,
        content_ref=f"oss://{signed['object_key']}",
        upload_url=None,
        upload_headers=upload_meta,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.workspace_upload_session_ttl_seconds),
    )
    db.add(session)
    await db.flush()
    _attach_transient_upload_authorization(session, signed)
    await audit(db, ws, "upload_initiated", admin_id=auth.id, metadata={"size": data.size, "path": path})
    return session


async def complete_direct_upload(
    db: AsyncSession, session: WorkspaceUploadSession, actor: CurrentUser | CurrentAdmin,
    *, client_etag: str | None = None, parts: list[dict] | None = None,
) -> WorkspaceFile:
    is_admin = isinstance(actor, CurrentAdmin)
    actor_matches = (
        session.admin_id == actor.id if is_admin else str(session.user_id or "") == str(actor.id)
    )
    if not actor_matches:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    if session.status == "completed" and session.workspace_file_id:
        existing = await db.get(WorkspaceFile, session.workspace_file_id)
        if existing:
            replay_version_id = str(
                (session.upload_headers or {}).get("result_version_id") or ""
            )
            if replay_version_id:
                setattr(existing, "mutation_result_version_id", UUID(replay_version_id))
            return existing
    if session.status != "pending" or session.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="上传会话已失效")
    ws = await workspace_service.get_workspace(db, session.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    upload_meta = dict(session.upload_headers or {})
    target_file_id = str(upload_meta.get("target_file_id") or "")
    base_version_id = str(upload_meta.get("base_version_id") or "")
    idempotency_key = str(upload_meta.get("idempotency_key") or "")
    replacing = bool(target_file_id and base_version_id and idempotency_key)
    if any((target_file_id, base_version_id, idempotency_key)) and not replacing:
        raise HTTPException(status_code=409, detail="上传会话的版本替换参数不完整")
    if not is_admin:
        if replacing:
            await workspace_permission_service.assert_can_update(db, ws, actor)
        else:
            await workspace_permission_service.assert_can_create(db, ws, actor)
    existing_path = await workspace_service.get_file_by_path(db, ws.id, session.path)
    replacement_target = None
    if replacing:
        try:
            replacement_target = await workspace_service.get_file(db, UUID(target_file_id))
            parsed_base_version_id = UUID(base_version_id)
        except (TypeError, ValueError):
            replacement_target = None
            parsed_base_version_id = None
        if (
            replacement_target is None
            or parsed_base_version_id is None
            or str(replacement_target.workspace_id) != str(ws.id)
            or replacement_target.path != session.path
            or existing_path is None
            or str(existing_path.id) != str(replacement_target.id)
        ):
            raise HTTPException(status_code=409, detail={
                "code": "workspace_file_replacement_target_mismatch",
                "message": "目标文件或路径已变化，请刷新后重试",
            })
    elif existing_path is not None:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_path_conflict",
            "message": "目标路径已存在；上传不能静默覆盖老文件",
            "file_id": str(existing_path.id),
            "current_version_id": (
                str(existing_path.current_version_id) if existing_path.current_version_id else None
            ),
        })
    transport = str(upload_meta.get("transport") or "put")
    completion_result: dict = {}
    try:
        if transport == "multipart":
            gateway_session_id = str(upload_meta.get("gateway_session_id") or "")
            if not gateway_session_id or not parts:
                raise HTTPException(status_code=422, detail="分片上传缺少完整回执")
            completion_result = await storage_gateway_service.complete_multipart_upload(
                gateway_session_id, parts,
            )
            client_etag = str(completion_result.get("etag") or client_etag or "")
        else:
            completion_result = await storage_gateway_service.finalize_policy_upload(
                storage_gateway_service.object_key_from_ref(str(session.content_ref)),
            )
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        actual = await storage_gateway_service.inspect_object(str(session.content_ref))
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if int(actual["size"]) != session.expected_size:
        session.status = "failed"
        session.error = f"对象大小不一致：期望 {session.expected_size}，实际 {actual['size']}"
        await db.flush()
        raise HTTPException(status_code=409, detail=session.error)
    server_etag = str(actual.get("etag") or "")
    if not server_etag:
        raise HTTPException(status_code=409, detail="对象缺少服务端 ETag，无法完成上传")
    if client_etag and server_etag and client_etag.strip('"') != server_etag:
        raise HTTPException(status_code=409, detail="对象 ETag 校验失败")
    completed_etag = str(completion_result.get("etag") or "").strip('"')
    if not completed_etag or completed_etag != server_etag:
        raise HTTPException(status_code=409, detail="对象完成回执与 HEAD 的 ETag 不一致")
    completed_size = int(completion_result.get("size") or 0)
    if completed_size != session.expected_size:
        raise HTTPException(status_code=409, detail="对象完成回执大小校验失败")
    actual_version_id = str(actual.get("version_id") or "") or None
    completed_version_id = str(completion_result.get("version_id") or "") or None
    if completed_version_id != actual_version_id:
        raise HTTPException(status_code=409, detail="对象完成回执与 HEAD 的版本不一致")
    integrity_algorithm = str(actual.get("integrity_algorithm") or "").lower()
    integrity_value = str(actual.get("integrity_value") or "")
    if integrity_algorithm != "crc64ecma" or not integrity_value.isdecimal():
        raise HTTPException(status_code=409, detail="对象缺少可信的 OSS CRC64 完整性校验")
    completed_integrity_algorithm = str(
        completion_result.get("integrity_algorithm") or ""
    ).lower()
    completed_integrity_value = str(completion_result.get("integrity_value") or "")
    if (
        completed_integrity_algorithm != integrity_algorithm
        or completed_integrity_value != integrity_value
    ):
        raise HTTPException(status_code=409, detail="对象完成回执与 HEAD 的 CRC64 不一致")
    actual_type = str(actual.get("content_type") or "").split(";", 1)[0].lower()
    expected_type = str(session.content_type or "application/octet-stream").split(";", 1)[0].lower()
    if actual_type and expected_type != "application/octet-stream" and actual_type != expected_type:
        session.status = "failed"
        session.error = f"对象类型不一致：期望 {expected_type}，实际 {actual_type}"
        await db.flush()
        raise HTTPException(status_code=409, detail=session.error)
    trusted_content_hash = str(actual.get("content_hash") or "").lower()
    if len(trusted_content_hash) != 64 or any(
        character not in "0123456789abcdef" for character in trusted_content_hash
    ):
        trusted_content_hash = None
    metadata = {
        "binary": True,
        "mime": session.content_type or actual.get("content_type") or "application/octet-stream",
        "name": session.original_filename,
        "storage_backend": "oss_gateway",
        "etag": server_etag,
        # Business objects use immutable per-version keys, so VersionId is
        # optional when OSS bucket versioning is disabled. WebOffice uses a
        # separate versioned bucket and enforces VersionId in its own worker.
        "storage_version_id": actual_version_id,
        "integrity_algorithm": integrity_algorithm,
        "integrity_value": integrity_value,
        **({
            "artifact_format_verified": True,
            "detected_artifact_format": str(actual.get("detected_format")),
        } if actual.get("format_verified") is True and actual.get("detected_format") else {}),
    }
    # Upload finalization can spend seconds completing multipart state and
    # verifying OSS.  A role/account revocation during that window must take
    # effect before the logical file is created or advanced.
    if is_admin:
        live_admin = await db.get(Admin, actor.id)
        if (
            live_admin is None
            or not live_admin.is_active
            or (
                live_admin.organization_id is not None
                and str(live_admin.organization_id) != str(ws.organization_id)
            )
        ):
            raise HTTPException(status_code=404, detail="工作空间不存在或无权访问")
    else:
        try:
            live_user = await db.get(User, UUID(str(actor.id)))
        except (TypeError, ValueError):
            live_user = None
        if (
            live_user is None
            or not live_user.is_active
            or live_user.deleted_at is not None
            or str(live_user.organization_id) != str(ws.organization_id)
        ):
            raise HTTPException(status_code=404, detail="工作空间不存在或无权访问")
        actor = await current_user_for_user(db, live_user)
        if replacing:
            await workspace_permission_service.assert_can_update(db, ws, actor)
        else:
            await workspace_permission_service.assert_can_create(db, ws, actor)
    try:
        if replacing:
            file = await workspace_service.replace_file_artifact(
                db,
                replacement_target,
                content=None,
                content_ref=session.content_ref,
                size=session.expected_size,
                content_hash=trusted_content_hash,
                metadata=metadata,
                parse_status="queued",
                parse_kind=None,
                base_version_id=parsed_base_version_id,
                idempotency_key=idempotency_key,
                expected_workspace_id=ws.id,
                expected_path=session.path,
                created_by_user_id=None if is_admin else actor.id,
                created_by_admin_id=actor.id if is_admin else None,
            )
        else:
            file = await workspace_service.upsert_file(
                db, ws, WorkspaceFileCreate(path=session.path, content="", metadata=metadata),
                content_ref=session.content_ref, raw_size=session.expected_size,
                raw_content_hash=trusted_content_hash,
                created_by_user_id=None if is_admin else actor.id,
                created_by_admin_id=actor.id if is_admin else None,
            )
            file.content = None
            file.parse_status = "queued"
            file.parse_kind = None
            file.parse_error = None
            await workspace_service.sync_current_version(db, file)
    except workspace_service.WorkspaceFileVersionConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_version_conflict",
            "message": str(exc),
            "current_version_id": exc.current_version_id,
        }) from exc
    except workspace_service.WorkspaceFileIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_idempotency_conflict",
            "message": str(exc),
        }) from exc
    except workspace_service.WorkspaceFileActiveEditConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_active_edit_conflict",
            "message": str(exc),
            "room_id": exc.room_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    except workspace_service.WorkspaceFileUnsupportedTextUpdate as exc:
        raise HTTPException(status_code=422, detail={
            "code": "workspace_file_artifact_format_mismatch",
            "message": str(exc),
        }) from exc
    except workspace_service.WorkspaceFilePathConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_path_conflict",
            "message": str(exc),
            "file_id": exc.file_id,
            "current_version_id": exc.current_version_id,
        }) from exc
    # Warm only durable, version-pinned preview artifacts. Small Word/Excel
    # files are parsed locally in the browser and never consume IMM calls.
    if int(file.size or 0) <= settings.workspace_weboffice_max_bytes:
        from app.services import workspace_preview_session_service

        suffix = PurePosixPath(session.original_filename).suffix.lower()
        if suffix in workspace_preview_session_service.PRESENTATION_SUFFIXES:
            await workspace_preview_session_service.enqueue_fallback(db, file)
        elif (
            suffix in workspace_preview_session_service.LEGACY_WORD_SUFFIXES
            or (
                suffix in workspace_preview_session_service.MODERN_WORD_SUFFIXES
                and int(file.size or 0) > workspace_preview_session_service.LOCAL_OFFICE_MAX_BYTES
            )
        ):
            await workspace_preview_session_service.enqueue_fallback(db, file)
        elif (
            (
                suffix in workspace_preview_session_service.SPREADSHEET_SUFFIXES
                and int(file.size or 0) > workspace_preview_session_service.LOCAL_OFFICE_MAX_BYTES
            )
            or (
                suffix in workspace_preview_session_service.TABULAR_TEXT_SUFFIXES
                and int(file.size or 0) > workspace_preview_session_service.TABULAR_TEXT_LOCAL_MAX_BYTES
            )
        ):
            await workspace_preview_session_service.enqueue_preview_job(
                db, file, conversion_type="spreadsheet_rows",
            )
    session.status = "completed"
    session.completed_at = datetime.now(UTC)
    session.workspace_file_id = file.id
    session.upload_url = None
    # Retain only non-secret replay identity. Signed URLs, headers and Gateway
    # session ids are discarded permanently.
    session.upload_headers = {
        "result_version_id": str(file.current_version_id) if file.current_version_id else None,
    }
    await audit(db, ws, "file_version_uploaded" if replacing else "upload_completed",
                user_id=None if is_admin else actor.id,
                admin_id=actor.id if is_admin else None, file=file, version_id=file.current_version_id,
                metadata={"size": file.size, "etag": server_etag})
    await db.flush()
    # ``updated_at`` is populated by a server-side ``onupdate`` expression.  The
    # final flush above therefore expires that attribute; refresh it before the
    # ORM object is handed to a FastAPI/Pydantic response model.  Without this,
    # successful direct uploads are committed but the response serialization
    # fails with a missing ``updated_at`` field.
    await db.refresh(file)
    return file


async def cancel_upload(
    db: AsyncSession, session: WorkspaceUploadSession, actor: CurrentUser | CurrentAdmin,
) -> None:
    is_admin = isinstance(actor, CurrentAdmin)
    actor_matches = session.admin_id == actor.id if is_admin else str(session.user_id or "") == str(actor.id)
    if not actor_matches:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    if session.status == "completed":
        raise HTTPException(status_code=409, detail="已完成的上传不能取消")
    upload_meta = dict(session.upload_headers or {})
    gateway_session_id = str(upload_meta.get("gateway_session_id") or "")
    if upload_meta.get("transport") == "multipart" and gateway_session_id:
        try:
            await storage_gateway_service.abort_multipart_upload(gateway_session_id)
        except storage_gateway_service.StorageGatewayError:
            pass
    elif session.content_ref:
        try:
            await storage_gateway_service.delete_object(session.content_ref)
        except storage_gateway_service.StorageGatewayError:
            pass
    session.status = "cancelled"
    session.upload_url = None
    session.upload_headers = {}
    await db.flush()


def _assert_upload_actor(session: WorkspaceUploadSession, actor: CurrentUser | CurrentAdmin) -> None:
    is_admin = isinstance(actor, CurrentAdmin)
    actor_matches = session.admin_id == actor.id if is_admin else str(session.user_id or "") == str(actor.id)
    if not actor_matches:
        raise HTTPException(status_code=404, detail="上传会话不存在")


def _multipart_gateway_session_id(session: WorkspaceUploadSession) -> str:
    upload_meta = dict(session.upload_headers or {})
    gateway_session_id = str(upload_meta.get("gateway_session_id") or "")
    if upload_meta.get("transport") != "multipart" or not gateway_session_id:
        raise HTTPException(status_code=409, detail="这不是分片上传会话")
    return gateway_session_id


async def sign_upload_part(
    session: WorkspaceUploadSession, actor: CurrentUser | CurrentAdmin, part_number: int,
) -> dict:
    _assert_upload_actor(session, actor)
    gateway_session_id = _multipart_gateway_session_id(session)
    try:
        return await storage_gateway_service.sign_multipart_part(gateway_session_id, part_number)
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def multipart_upload_status(
    session: WorkspaceUploadSession, actor: CurrentUser | CurrentAdmin,
) -> dict:
    _assert_upload_actor(session, actor)
    gateway_session_id = _multipart_gateway_session_id(session)
    try:
        return await storage_gateway_service.get_multipart_status(gateway_session_id)
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def list_versions(db: AsyncSession, file: WorkspaceFile) -> list[WorkspaceFileVersion]:
    return list((await db.execute(select(WorkspaceFileVersion).where(
        WorkspaceFileVersion.workspace_file_id == file.id,
    ).order_by(WorkspaceFileVersion.version_no.desc()))).scalars().all())


async def restore_version(
    db: AsyncSession, ws: Workspace, file: WorkspaceFile, version: WorkspaceFileVersion, cu: CurrentUser,
) -> WorkspaceFile:
    await workspace_permission_service.assert_can_manage(db, ws, cu)
    if version.workspace_file_id != file.id:
        raise HTTPException(status_code=404, detail="文件版本不存在")
    for field in (
        "size", "content_hash", "content_ref", "content", "extracted_text",
        "parse_status", "parse_kind", "parse_error", "metadata_",
    ):
        setattr(file, field, getattr(version, field))
    await workspace_service.create_file_version(db, file, created_by_user_id=cu.id)
    await audit(db, ws, "version_restored", user_id=cu.id, file=file,
                version_id=file.current_version_id, metadata={"restored_from": str(version.id)})
    await db.refresh(file)
    return file


async def restore_version_admin(
    db: AsyncSession,
    ws: Workspace,
    file: WorkspaceFile,
    version: WorkspaceFileVersion,
    admin: CurrentAdmin,
) -> WorkspaceFile:
    """Restore an immutable file version through the administrator API."""
    if version.workspace_file_id != file.id:
        raise HTTPException(status_code=404, detail="文件版本不存在")
    for field in (
        "size", "content_hash", "content_ref", "content", "extracted_text",
        "parse_status", "parse_kind", "parse_error", "metadata_",
    ):
        setattr(file, field, getattr(version, field))
    await workspace_service.create_file_version(db, file, created_by_admin_id=admin.id)
    await audit(
        db,
        ws,
        "version_restored",
        admin_id=admin.id,
        file=file,
        version_id=file.current_version_id,
        metadata={"restored_from": str(version.id)},
    )
    await db.refresh(file)
    return file


async def list_trash(db: AsyncSession, ws: Workspace) -> list[WorkspaceFile]:
    return list((await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.workspace_id == ws.id, WorkspaceFile.deleted_at.is_not(None),
    ).order_by(WorkspaceFile.deleted_at.desc()))).scalars().all())


async def list_audit_events(
    db: AsyncSession, ws: Workspace, *, limit: int = 200,
) -> list[WorkspaceAuditEvent]:
    events = list((await db.execute(select(WorkspaceAuditEvent).where(
        WorkspaceAuditEvent.workspace_id == ws.id,
    ).order_by(WorkspaceAuditEvent.created_at.desc()).limit(limit))).scalars().all())
    user_ids = {event.actor_user_id for event in events if event.actor_user_id}
    admin_ids = {event.actor_admin_id for event in events if event.actor_admin_id is not None}
    users = {
        str(user.id): user
        for user in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    } if user_ids else {}
    admins = {
        admin.id: admin
        for admin in (await db.execute(select(Admin).where(Admin.id.in_(admin_ids)))).scalars().all()
    } if admin_ids else {}
    for event in events:
        user = users.get(str(event.actor_user_id)) if event.actor_user_id else None
        admin = admins.get(event.actor_admin_id) if event.actor_admin_id is not None else None
        actor = user or admin
        event.actor_display_name = (actor.display_name or actor.username) if actor else "系统"
    return events


async def _restore_from_trash(
    db: AsyncSession,
    ws: Workspace,
    file_id: UUID,
    *,
    base_version_id: UUID,
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
    user_id: str | UUID | None = None,
    admin_id: int | None = None,
) -> WorkspaceFile:
    """Restore one tombstone with row locking and durable replay semantics."""
    file = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id == file_id,
        WorkspaceFile.workspace_id == ws.id,
    ).with_for_update())).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="回收站文件不存在")
    try:
        mutation, replayed = await workspace_service.begin_file_mutation(
            db,
            workspace=ws,
            file=file,
            actor_type=actor_type,
            actor_id=actor_id,
            operation="trash_restore",
            idempotency_key=idempotency_key,
            base_version_id=base_version_id,
            payload={
                "file_id": str(file.id),
                "workspace_id": str(ws.id),
                "base_version_id": str(base_version_id),
            },
        )
    except workspace_service.WorkspaceFileIdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_idempotency_conflict",
            "message": str(exc),
        }) from exc
    if replayed:
        if mutation.result_file_id != file.id or not mutation.result_version_id:
            raise HTTPException(status_code=409, detail="幂等恢复结果已不可用")
        try:
            snapshot, _ = await workspace_service.file_snapshot_at_version(
                db, file, UUID(str(mutation.result_version_id)),
            )
        except (TypeError, ValueError, workspace_service.WorkspaceFileVersionNotFound) as exc:
            raise HTTPException(status_code=409, detail="幂等恢复结果已不可用") from exc
        result = dict(mutation.result or {})
        snapshot.path = str(result.get("path") or snapshot.path)
        snapshot.workspace_id = ws.id
        snapshot.metadata_ = dict(snapshot.metadata_ or {})
        snapshot.metadata_["name"] = PurePosixPath(snapshot.path).name
        snapshot.is_mutation_replay = True
        snapshot.mutation_result_version_id = mutation.result_version_id
        return snapshot
    if file.deleted_at is None:
        await db.delete(mutation)
        await db.flush()
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_not_deleted",
            "message": "文件已经恢复",
            "current_version_id": str(file.current_version_id) if file.current_version_id else None,
        })
    if str(file.current_version_id or "") != str(base_version_id):
        await db.delete(mutation)
        await db.flush()
        raise HTTPException(status_code=409, detail={
            "code": "workspace_file_version_conflict",
            "message": "回收站文件版本已变化，请刷新后重试",
            "current_version_id": str(file.current_version_id) if file.current_version_id else None,
        })
    occupied = await workspace_service.get_file_by_path(db, ws.id, file.path)
    if occupied is not None and str(occupied.id) != str(file.id):
        await db.delete(mutation)
        await db.flush()
        raise HTTPException(
            status_code=409,
            detail="同路径已有新文件，请先重命名当前文件再恢复",
        )
    try:
        async with db.begin_nested():
            restore(file)
            file.deleted_by_user_id = None
            file.deleted_by_admin_id = None
            await db.flush()
    except IntegrityError:
        # The partial unique index is authoritative if another generation won
        # the path after our preflight.  Keep the outer session usable and do
        # not strand a pending idempotency claim.
        await db.delete(mutation)
        await db.flush()
        raise HTTPException(
            status_code=409,
            detail="同路径已有新文件，请刷新后重试",
        ) from None
    await workspace_service.enqueue_file_event(
        db, file, event_type="file_restored", version_id=file.current_version_id,
    )
    await audit(
        db,
        ws,
        "file_restored",
        user_id=user_id,
        admin_id=admin_id,
        file=file,
        version_id=file.current_version_id,
    )
    await workspace_service.complete_file_mutation(
        db,
        mutation,
        result_file=file,
        result={
            "file_id": str(file.id),
            "workspace_id": str(ws.id),
            "path": file.path,
            "restored": True,
        },
    )
    await db.refresh(file)
    return file


async def restore_from_trash(
    db: AsyncSession,
    ws: Workspace,
    file_id: UUID,
    cu: CurrentUser,
    *,
    base_version_id: UUID,
    idempotency_key: str,
) -> WorkspaceFile:
    await workspace_permission_service.assert_can_delete(db, ws, cu)
    return await _restore_from_trash(
        db,
        ws,
        file_id,
        base_version_id=base_version_id,
        idempotency_key=idempotency_key,
        actor_type="user",
        actor_id=str(cu.id),
        user_id=cu.id,
    )


async def restore_from_trash_admin(
    db: AsyncSession,
    ws: Workspace,
    file_id: UUID,
    admin: CurrentAdmin,
    *,
    base_version_id: UUID,
    idempotency_key: str,
) -> WorkspaceFile:
    """Restore a deleted file through the administrator API."""
    return await _restore_from_trash(
        db,
        ws,
        file_id,
        base_version_id=base_version_id,
        idempotency_key=idempotency_key,
        actor_type="admin",
        actor_id=str(admin.id),
        admin_id=admin.id,
    )


async def publish_file(
    db: AsyncSession, source_ws: Workspace, source: WorkspaceFile,
    target_ws: Workspace, cu: CurrentUser, target_path: str | None,
) -> WorkspaceFile:
    await workspace_permission_service.assert_can_publish(db, source_ws, cu)
    await workspace_permission_service.assert_publish_target(db, target_ws, cu)
    if source.workspace_id != source_ws.id:
        raise HTTPException(status_code=404, detail="文件不存在")
    base_name = str((source.metadata_ or {}).get("name") or PurePosixPath(source.path).name)
    path = workspace_service._normalize_path(target_path or base_name)
    existing = await workspace_service.get_file_by_path(db, target_ws.id, path)
    if existing is not None:
        p = PurePosixPath(path)
        path = str(p.with_name(f"{p.stem}-{datetime.now(UTC):%Y%m%d%H%M%S}-{secrets.token_hex(3)}{p.suffix}"))
    clone = await workspace_service.upsert_file(
        db,
        target_ws,
        WorkspaceFileCreate(path=path, content=source.content or "", metadata=dict(source.metadata_ or {})),
        content_ref=source.content_ref,
        raw_size=source.size,
        raw_content_hash=source.content_hash,
        created_by_user_id=cu.id,
    )
    clone.extracted_text = source.extracted_text
    clone.parse_status = source.parse_status
    clone.parse_kind = source.parse_kind
    clone.parse_error = source.parse_error
    await workspace_service.sync_current_version(db, clone)
    await audit(
        db,
        source_ws,
        "file_published",
        user_id=cu.id,
        file=source,
        version_id=source.current_version_id,
        metadata={"target_workspace_id": str(target_ws.id), "target_file_id": str(clone.id)},
    )
    await audit(
        db,
        target_ws,
        "file_received",
        user_id=cu.id,
        file=clone,
        version_id=clone.current_version_id,
        metadata={"source_file_id": str(source.id)},
    )
    await db.refresh(clone)
    return clone


async def create_share(
    db: AsyncSession, ws: Workspace, file: WorkspaceFile, cu: CurrentUser, expires_in_seconds: int,
) -> tuple[str, datetime]:
    await workspace_permission_service.assert_can_manage(db, ws, cu)
    if not file.current_version_id:
        raise HTTPException(status_code=409, detail="文件没有可分享版本")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
    db.add(WorkspaceShareLink(
        workspace_file_id=file.id,
        version_id=file.current_version_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=expires_at,
        created_by_user_id=cu.id,
    ))
    await audit(db, ws, "share_created", user_id=cu.id, file=file, version_id=file.current_version_id,
                metadata={"expires_at": expires_at.isoformat()})
    return token, expires_at


async def resolve_share(db: AsyncSession, token: str) -> tuple[WorkspaceFileVersion, str, str]:
    link = (await db.execute(select(WorkspaceShareLink).where(
        WorkspaceShareLink.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        WorkspaceShareLink.revoked_at.is_(None), WorkspaceShareLink.expires_at > datetime.now(UTC),
    ))).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="分享链接不存在或已过期")
    version = await db.get(WorkspaceFileVersion, link.version_id)
    file = await db.get(WorkspaceFile, link.workspace_file_id)
    if version is None or file is None:
        raise HTTPException(status_code=404, detail="分享文件不存在")
    name = str((version.metadata_ or {}).get("name") or PurePosixPath(file.path).name)
    mime = str((version.metadata_ or {}).get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream")
    return version, name, mime


async def load_version_bytes(version: WorkspaceFileVersion) -> bytes:
    if storage_gateway_service.is_object_ref(version.content_ref):
        return await storage_gateway_service.download_bytes(
            str(version.content_ref),
            version_id=(
                str(version.storage_version_id)
                if version.storage_version_id
                else str((version.metadata_ or {}).get("storage_version_id") or "") or None
            ),
        )
    if (version.metadata_ or {}).get("binary"):
        return base64.b64decode(version.content or "", validate=False)
    return (version.content or "").encode("utf-8")


async def purge_expired(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    rows = list((await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.deleted_at.is_not(None), WorkspaceFile.purge_after <= now,
    ).limit(50))).scalars().all())
    purged = 0
    for file in rows:
        active_shares = int((await db.scalar(select(func.count()).select_from(WorkspaceShareLink).where(
            WorkspaceShareLink.workspace_file_id == file.id,
            WorkspaceShareLink.revoked_at.is_(None),
            WorkspaceShareLink.expires_at > now,
        ))) or 0)
        if active_shares:
            continue
        refs = {str(version.content_ref) for version in await list_versions(db, file) if version.content_ref}
        preview_refs = (await db.execute(select(WorkspacePreviewJob.output_ref).where(
            WorkspacePreviewJob.workspace_file_id == file.id,
            WorkspacePreviewJob.output_ref.is_not(None),
        ))).scalars().all()
        refs.update(str(ref) for ref in preview_refs if ref)
        if file.content_ref:
            refs.add(str(file.content_ref))
        can_purge = True
        for ref in refs:
            if not storage_gateway_service.is_object_ref(ref):
                continue
            other_files = int((await db.scalar(select(func.count()).select_from(WorkspaceFile).where(
                WorkspaceFile.id != file.id, WorkspaceFile.content_ref == ref,
            ))) or 0)
            other_versions = int((await db.scalar(select(func.count()).select_from(WorkspaceFileVersion).where(
                WorkspaceFileVersion.workspace_file_id != file.id, WorkspaceFileVersion.content_ref == ref,
            ))) or 0)
            if other_files or other_versions:
                continue
            try:
                await storage_gateway_service.delete_object(ref)
            except storage_gateway_service.StorageGatewayError:
                file.metadata_ = {
                    **(file.metadata_ or {}),
                    "lifecycle_cleanup_error": "OSS delete failed; retry scheduled",
                    "lifecycle_cleanup_failed_at": datetime.now(UTC).isoformat(),
                }
                can_purge = False
                break
        if not can_purge:
            continue
        await db.delete(file)
        purged += 1
    await db.flush()
    return purged
