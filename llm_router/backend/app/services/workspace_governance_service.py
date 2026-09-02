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
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin_auth import CurrentAdmin
from app.auth.user_auth import CurrentUser
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
        raise HTTPException(status_code=413, detail="文件超过 100MB 上限")


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


async def initiate_direct_upload(
    db: AsyncSession, ws: Workspace, cu: CurrentUser, data: WorkspaceUploadInitiate,
) -> WorkspaceUploadSession:
    await workspace_permission_service.assert_can_create(db, ws, cu)
    if not settings.workspace_hybrid_upload_enabled:
        raise HTTPException(status_code=503, detail="新版上传链路已由部署级开关暂时关闭")
    if not settings.workspace_object_storage_configured:
        raise HTTPException(status_code=503, detail="大文件上传要求已配置对象存储")
    _validate_direct_upload_size(data.size)
    path = workspace_service._normalize_path(data.path)
    if not path:
        raise HTTPException(status_code=422, detail="文件路径不能为空")
    try:
        signed = await storage_gateway_service.sign_browser_upload(
            filename=data.filename, content_type=data.content_type, size_bytes=data.size,
            weak_network=data.weak_network,
        )
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    upload_meta = {
        "transport": str(signed.get("method") or "PUT").lower(),
        "headers": dict(signed.get("headers") or {}),
        "fallback_url": signed.get("fallback_url"),
        "gateway_session_id": signed.get("gateway_session_id"),
        "part_size": signed.get("part_size"),
        "expected_parts": signed.get("expected_parts"),
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
        upload_url=signed.get("url"),
        upload_headers=upload_meta,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.workspace_upload_session_ttl_seconds),
    )
    db.add(session)
    await db.flush()
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
    try:
        signed = await storage_gateway_service.sign_browser_upload(
            filename=data.filename, content_type=data.content_type, size_bytes=data.size,
            weak_network=data.weak_network,
        )
    except storage_gateway_service.StorageGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    upload_meta = {
        "transport": str(signed.get("method") or "PUT").lower(),
        "headers": dict(signed.get("headers") or {}),
        "fallback_url": signed.get("fallback_url"),
        "gateway_session_id": signed.get("gateway_session_id"),
        "part_size": signed.get("part_size"),
        "expected_parts": signed.get("expected_parts"),
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
        upload_url=signed.get("url"),
        upload_headers=upload_meta,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.workspace_upload_session_ttl_seconds),
    )
    db.add(session)
    await db.flush()
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
            return existing
    if session.status != "pending" or session.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="上传会话已失效")
    ws = await workspace_service.get_workspace(db, session.workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    if not is_admin:
        await workspace_permission_service.assert_can_create(db, ws, actor)
    transport = str((session.upload_headers or {}).get("transport") or "put")
    try:
        if transport == "multipart":
            gateway_session_id = str((session.upload_headers or {}).get("gateway_session_id") or "")
            if not gateway_session_id or not parts:
                raise HTTPException(status_code=422, detail="分片上传缺少完整回执")
            result = await storage_gateway_service.complete_multipart_upload(gateway_session_id, parts)
            client_etag = str(result.get("etag") or client_etag or "")
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
    if client_etag and server_etag and client_etag.strip('"') != server_etag:
        raise HTTPException(status_code=409, detail="对象 ETag 校验失败")
    actual_type = str(actual.get("content_type") or "").split(";", 1)[0].lower()
    expected_type = str(session.content_type or "application/octet-stream").split(";", 1)[0].lower()
    if actual_type and expected_type != "application/octet-stream" and actual_type != expected_type:
        session.status = "failed"
        session.error = f"对象类型不一致：期望 {expected_type}，实际 {actual_type}"
        await db.flush()
        raise HTTPException(status_code=409, detail=session.error)
    metadata = {
        "binary": True,
        "mime": session.content_type or actual.get("content_type") or "application/octet-stream",
        "name": session.original_filename,
        "storage_backend": "oss_gateway",
        "etag": server_etag,
    }
    file = await workspace_service.upsert_file(
        db, ws, WorkspaceFileCreate(path=session.path, content="", metadata=metadata),
        content_ref=session.content_ref, raw_size=session.expected_size, raw_content_hash=None,
        created_by_user_id=None if is_admin else actor.id,
        created_by_admin_id=actor.id if is_admin else None,
    )
    file.content = None
    file.parse_status = "queued"
    file.parse_kind = None
    file.parse_error = None
    await workspace_service.sync_current_version(db, file)
    session.status = "completed"
    session.completed_at = datetime.now(UTC)
    session.workspace_file_id = file.id
    session.upload_url = None
    session.upload_headers = {}
    await audit(db, ws, "upload_completed", user_id=None if is_admin else actor.id,
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


async def restore_from_trash(db: AsyncSession, ws: Workspace, file_id: UUID, cu: CurrentUser) -> WorkspaceFile:
    await workspace_permission_service.assert_can_delete(db, ws, cu)
    file = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id == file_id, WorkspaceFile.workspace_id == ws.id,
        WorkspaceFile.deleted_at.is_not(None),
    ))).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="回收站文件不存在")
    restore(file)
    file.deleted_by_user_id = None
    file.deleted_by_admin_id = None
    await audit(db, ws, "file_restored", user_id=cu.id, file=file, version_id=file.current_version_id)
    await db.refresh(file)
    return file


async def restore_from_trash_admin(
    db: AsyncSession, ws: Workspace, file_id: UUID, admin: CurrentAdmin,
) -> WorkspaceFile:
    """Restore a deleted file through the administrator API."""
    file = (await db.execute(select(WorkspaceFile).where(
        WorkspaceFile.id == file_id,
        WorkspaceFile.workspace_id == ws.id,
        WorkspaceFile.deleted_at.is_not(None),
    ))).scalar_one_or_none()
    if file is None:
        raise HTTPException(status_code=404, detail="回收站文件不存在")
    restore(file)
    file.deleted_by_user_id = None
    file.deleted_by_admin_id = None
    await audit(
        db, ws, "file_restored", admin_id=admin.id,
        file=file, version_id=file.current_version_id,
    )
    await db.refresh(file)
    return file


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
        return await storage_gateway_service.download_bytes(str(version.content_ref))
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
