"""Tenant-safe audio job queue and enterprise voice authorization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.admin_auth import CurrentAdmin, assert_org_write_access
from app.auth.user_auth import CurrentUser
from app.config import settings
from app.models.department import Department
from app.models.multimodal import (
    MultimodalJob,
    VoiceAuthorizationRecord,
    VoiceProfile,
    VoiceProfileGrant,
)
from app.models.organization import Organization
from app.models.role import Role
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceFile
from app.schemas.multimodal import (
    AudioTranscriptionCreate,
    SpeechCreate,
    VoiceBuiltinCreate,
    VoiceCloneCreate,
    VoiceDesignCreate,
    VoiceGrantInput,
    VoiceProfileUpdate,
)
from app.services import model_gateway, storage_gateway_service
from app.services.scope_service import effective_scope_set, is_workspace_visible


def require_permission(cu: CurrentUser, code: str) -> None:
    permissions = set(cu.permission_codes or ())
    if "*" not in permissions and code not in permissions:
        raise HTTPException(status_code=403, detail=f"Permission required: {code}")


async def require_multimodal_enabled(db: AsyncSession, organization_id: UUID) -> None:
    organization = await db.get(Organization, organization_id)
    if organization is None or not settings.multimodal_audio_enabled_for(
        organization.slug, organization_id=organization.id
    ):
        raise HTTPException(status_code=404, detail="Multimodal audio is not enabled for this organization")


async def _visible_audio_file(db: AsyncSession, cu: CurrentUser, file_id: UUID) -> WorkspaceFile:
    row = (await db.execute(
        select(WorkspaceFile)
        .options(selectinload(WorkspaceFile.workspace))
        .where(WorkspaceFile.id == file_id, WorkspaceFile.deleted_at.is_(None))
    )).scalar_one_or_none()
    if row is None or row.workspace is None:
        raise HTTPException(status_code=404, detail="Workspace file not found")
    if str(row.workspace.organization_id) != str(cu.organization_id) or not is_workspace_visible(row.workspace, cu):
        raise HTTPException(status_code=403, detail="Workspace file is not available to this user")
    if not row.content_ref:
        raise HTTPException(status_code=422, detail="Audio file is not stored in object storage")
    suffix = row.path.rsplit(".", 1)[-1].lower() if "." in row.path else ""
    if suffix not in {"mp3", "wav", "m4a", "webm", "opus"}:
        raise HTTPException(status_code=422, detail="Unsupported audio format")
    return row


def _idempotency_key(explicit: str | None, capability: str, payload: dict) -> str:
    if explicit:
        return explicit
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"auto:{capability}:{hashlib.sha256(canonical.encode()).hexdigest()}"


async def _create_job(
    db: AsyncSession,
    cu: CurrentUser,
    *,
    capability: str,
    input_file_id: UUID | None,
    voice_profile_id: UUID | None,
    params: dict,
    idempotency_key: str | None,
) -> MultimodalJob:
    key = _idempotency_key(idempotency_key, capability, params)
    existing = (await db.execute(select(MultimodalJob).where(
        MultimodalJob.organization_id == cu.organization_id,
        MultimodalJob.user_id == UUID(cu.id),
        MultimodalJob.idempotency_key == key,
    ))).scalar_one_or_none()
    if existing is not None:
        if existing.capability != capability or existing.params != params:
            raise HTTPException(status_code=409, detail="Idempotency key was used with different parameters")
        return existing
    now = datetime.now(UTC)
    cached = (await db.execute(select(MultimodalJob).where(
        MultimodalJob.organization_id == cu.organization_id,
        MultimodalJob.capability == capability,
        MultimodalJob.idempotency_key == key,
        MultimodalJob.params == params,
        MultimodalJob.status == "succeeded",
    ).order_by(MultimodalJob.finished_at.desc()).limit(1))).scalar_one_or_none()
    if cached is None:
        active_count = int((await db.scalar(select(func.count(MultimodalJob.id)).where(
            MultimodalJob.user_id == UUID(cu.id),
            MultimodalJob.status.in_(["queued", "processing"]),
        ))) or 0)
        if active_count >= settings.multimodal_user_concurrency:
            raise HTTPException(status_code=429, detail="Too many concurrent audio jobs")
    job = MultimodalJob(
        organization_id=cu.organization_id,
        user_id=UUID(cu.id),
        department_id=UUID(cu.department_id) if cu.department_id else None,
        capability=capability,
        input_file_id=input_file_id,
        voice_profile_id=voice_profile_id,
        status="succeeded" if cached is not None else "queued",
        request_id=str(uuid4()),
        idempotency_key=key,
        params=params,
        result={},
        usage={},
        available_at=now,
    )
    if cached is not None:
        job.deployment_id = cached.deployment_id
        job.output_file_ref = cached.output_file_ref
        job.result = dict(cached.result or {})
        job.usage = {**dict(cached.usage or {}), "cache_hit": True}
        job.audio_duration_ms = cached.audio_duration_ms
        job.latency_ms = 0
        job.finished_at = now
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def queue_transcription(
    db: AsyncSession, cu: CurrentUser, data: AudioTranscriptionCreate,
) -> MultimodalJob:
    await require_multimodal_enabled(db, UUID(str(cu.organization_id)))
    require_permission(cu, "multimodal.audio.transcribe")
    file = await _visible_audio_file(db, cu, data.workspace_file_id)
    return await _create_job(
        db,
        cu,
        capability="speech_to_text",
        input_file_id=file.id,
        voice_profile_id=None,
        params={
            "language": data.language,
            "model": data.model,
            "path": file.path,
            "workspace_file_id": str(file.id),
            "content_ref_hash": hashlib.sha256(str(file.content_ref).encode()).hexdigest(),
        },
        idempotency_key=data.idempotency_key,
    )


def _voice_scope_condition(cu: CurrentUser):
    scopes = effective_scope_set(cu)
    branches = []
    for scope_type, scope_id in scopes:
        if scope_type == "organization":
            branches.append((VoiceProfileGrant.scope_type == "organization") & (VoiceProfileGrant.scope_id.is_(None)))
        elif scope_type in {"role", "department", "user"} and scope_id:
            branches.append(
                (VoiceProfileGrant.scope_type == scope_type) & (VoiceProfileGrant.scope_id == str(scope_id))
            )
    return or_(*branches)


async def list_visible_voices(db: AsyncSession, cu: CurrentUser) -> list[VoiceProfile]:
    await require_multimodal_enabled(db, UUID(str(cu.organization_id)))
    require_permission(cu, "multimodal.speech.use")
    statement = (
        select(VoiceProfile)
        .join(VoiceProfileGrant, VoiceProfileGrant.voice_profile_id == VoiceProfile.id)
        .options(selectinload(VoiceProfile.grants))
        .where(
            VoiceProfile.organization_id == cu.organization_id,
            VoiceProfile.status == "active",
            VoiceProfile.deleted_at.is_(None),
            VoiceProfileGrant.deleted_at.is_(None),
            _voice_scope_condition(cu),
        )
        .distinct()
        .order_by(VoiceProfile.name)
    )
    voices = list((await db.execute(statement)).scalars().all())
    now = datetime.now(UTC)
    visible: list[VoiceProfile] = []
    for voice in voices:
        if voice.voice_type != "cloned":
            visible.append(voice)
            continue
        authorization = (await db.execute(select(VoiceAuthorizationRecord).where(
            VoiceAuthorizationRecord.voice_profile_id == voice.id,
            VoiceAuthorizationRecord.revoked_at.is_(None),
            VoiceAuthorizationRecord.valid_until > now,
        ))).scalar_one_or_none()
        if authorization:
            visible.append(voice)
    return visible


async def get_visible_voice(db: AsyncSession, cu: CurrentUser, voice_id: UUID) -> VoiceProfile:
    voices = await list_visible_voices(db, cu)
    voice = next((item for item in voices if item.id == voice_id), None)
    if voice is None:
        raise HTTPException(status_code=403, detail="Voice is not available to this user")
    return voice


async def queue_speech(db: AsyncSession, cu: CurrentUser, data: SpeechCreate) -> MultimodalJob:
    voice = await get_visible_voice(db, cu, data.voice_profile_id)
    capability = {
        "builtin": "text_to_speech",
        "designed": "voice_design",
        "cloned": "voice_clone",
    }[voice.voice_type]
    params = {
        "text": data.text,
        "style": data.style,
        "speed": data.speed,
        "format": data.format,
        "model": data.model,
        "voice_profile_id": str(voice.id),
        "voice_type": voice.voice_type,
        "provider_voice_id": voice.provider_voice_id,
        "design_prompt": voice.design_prompt,
    }
    return await _create_job(
        db,
        cu,
        capability=capability,
        input_file_id=voice.sample_file_id if voice.voice_type == "cloned" else None,
        voice_profile_id=voice.id,
        params=params,
        idempotency_key=data.idempotency_key,
    )


async def understand_file(
    db: AsyncSession,
    cu: CurrentUser,
    file_id: UUID,
    question: str,
    model: str,
) -> dict:
    await require_multimodal_enabled(db, UUID(str(cu.organization_id)))
    require_permission(cu, "multimodal.audio.understand")
    file = await _visible_audio_file(db, cu, file_id)
    signed = await storage_gateway_service.get_browser_signed_download(file.content_ref)
    result = await model_gateway.understand_audio(
        db,
        cu.organization_id,
        signed["url"],
        question,
        model_alias=model,
        dept_id=cu.department_id,
        team_id=cu.team_id,
    )
    return {
        "content": result.content or result.reasoning_content or "",
        "reasoning_content": result.reasoning_content,
        "model": result.model_served,
        "usage": result.usage,
        "request_id": str(uuid4()),
    }


async def stream_understand_file(
    db: AsyncSession,
    cu: CurrentUser,
    file_id: UUID,
    question: str,
    model: str,
) -> AsyncIterator[tuple[str, object, object]]:
    """Stream tenant-checked audio understanding from a short-lived OSS URL."""
    await require_multimodal_enabled(db, UUID(str(cu.organization_id)))
    require_permission(cu, "multimodal.audio.understand")
    file = await _visible_audio_file(db, cu, file_id)
    signed = await storage_gateway_service.get_browser_signed_download(file.content_ref)
    return model_gateway.stream_understand_audio(
        db,
        cu.organization_id,
        signed["url"],
        question,
        model_alias=model,
        dept_id=cu.department_id,
        team_id=cu.team_id,
    )


async def get_job(db: AsyncSession, cu: CurrentUser, job_id: UUID) -> MultimodalJob:
    await require_multimodal_enabled(db, UUID(str(cu.organization_id)))
    job = await db.get(MultimodalJob, job_id)
    permissions = set(cu.permission_codes or ())
    can_manage = "*" in permissions or "multimodal.voice.manage" in permissions
    if job is None or str(job.organization_id) != str(cu.organization_id):
        raise HTTPException(status_code=404, detail="Audio job not found")
    if str(job.user_id) != cu.id and not can_manage:
        raise HTTPException(status_code=403, detail="Audio job is not available to this user")
    return job


async def job_read_payload(db: AsyncSession, cu: CurrentUser, job_id: UUID) -> dict:
    """Return a tenant-checked job without exposing the internal OSS object key."""
    job = await get_job(db, cu, job_id)
    output_url = None
    if job.status == "succeeded" and job.output_file_ref:
        signed = await storage_gateway_service.get_browser_signed_download(job.output_file_ref)
        output_url = signed["url"]
    result = dict(job.result or {})
    result.pop("output_file_ref", None)
    return {
        "id": job.id,
        "organization_id": job.organization_id,
        "user_id": job.user_id,
        "capability": job.capability,
        "status": job.status,
        "request_id": job.request_id,
        "input_file_id": job.input_file_id,
        "output_url": output_url,
        "voice_profile_id": job.voice_profile_id,
        "result": result,
        "usage": job.usage or {},
        "attempts": job.attempts,
        "audio_duration_ms": job.audio_duration_ms,
        "latency_ms": job.latency_ms,
        "error_category": job.error_category,
        "error_detail": job.error_detail,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "finished_at": job.finished_at,
    }


async def _validate_grants(db: AsyncSession, org_id: UUID, grants: list[VoiceGrantInput]) -> None:
    for grant in grants:
        if grant.scope_type == "organization":
            continue
        assert grant.scope_id is not None
        if grant.scope_type == "role":
            target = await db.get(Role, grant.scope_id)
        elif grant.scope_type == "department":
            target = await db.get(Department, grant.scope_id)
        else:
            target = await db.get(User, grant.scope_id)
        if target is None or str(target.organization_id) != str(org_id):
            raise HTTPException(status_code=422, detail=f"Invalid {grant.scope_type} voice grant")


async def _replace_grants(
    db: AsyncSession, profile: VoiceProfile, grants: list[VoiceGrantInput],
) -> None:
    await _validate_grants(db, UUID(str(profile.organization_id)), grants)
    for existing in list(profile.grants):
        await db.delete(existing)
    for grant in grants or [VoiceGrantInput(scope_type="organization")]:
        db.add(VoiceProfileGrant(
            voice_profile_id=profile.id,
            organization_id=profile.organization_id,
            scope_type=grant.scope_type,
            scope_id=str(grant.scope_id) if grant.scope_id else None,
        ))
    await db.flush()
    await db.refresh(profile)


async def create_builtin_voice(
    db: AsyncSession, org_id: UUID, auth: CurrentAdmin, data: VoiceBuiltinCreate,
) -> VoiceProfile:
    assert_org_write_access(auth, org_id)
    profile = VoiceProfile(
        organization_id=org_id,
        created_by_admin_id=auth.id,
        name=data.name,
        voice_type="builtin",
        provider_voice_id=data.provider_voice_id,
        status="active",
        config={},
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    await _replace_grants(db, profile, data.grants)
    return profile


async def create_designed_voice(
    db: AsyncSession, org_id: UUID, auth: CurrentAdmin, data: VoiceDesignCreate,
) -> VoiceProfile:
    assert_org_write_access(auth, org_id)
    profile = VoiceProfile(
        organization_id=org_id,
        created_by_admin_id=auth.id,
        name=data.name,
        voice_type="designed",
        design_prompt=data.design_prompt,
        status="active",
        config={},
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    await _replace_grants(db, profile, data.grants)
    return profile


async def create_cloned_voice(
    db: AsyncSession, org_id: UUID, auth: CurrentAdmin, data: VoiceCloneCreate,
) -> VoiceProfile:
    assert_org_write_access(auth, org_id)
    now = datetime.now(UTC)
    if data.valid_until <= now:
        raise HTTPException(status_code=422, detail="Voice authorization has already expired")
    rows = list((await db.execute(
        select(WorkspaceFile, Workspace)
        .join(Workspace, Workspace.id == WorkspaceFile.workspace_id)
        .where(
            WorkspaceFile.id.in_([data.sample_file_id, data.evidence_file_id]),
            WorkspaceFile.deleted_at.is_(None),
            Workspace.organization_id == org_id,
            Workspace.deleted_at.is_(None),
        )
    )).all())
    files = {row.id: row for row, _ in rows}
    if set(files) != {data.sample_file_id, data.evidence_file_id}:
        raise HTTPException(status_code=422, detail="Voice sample or authorization evidence is invalid")
    sample = files[data.sample_file_id]
    evidence = files[data.evidence_file_id]
    if not sample.content_ref or not evidence.content_ref:
        raise HTTPException(status_code=422, detail="Voice sample and evidence must be stored in OSS")
    digest_source = evidence.content_hash or evidence.content_ref
    profile = VoiceProfile(
        organization_id=org_id,
        created_by_admin_id=auth.id,
        name=data.name,
        voice_type="cloned",
        sample_file_id=sample.id,
        status="active",
        config={},
    )
    db.add(profile)
    await db.flush()
    db.add(VoiceAuthorizationRecord(
        voice_profile_id=profile.id,
        organization_id=org_id,
        rights_holder=data.rights_holder,
        purpose=data.purpose,
        evidence_file_id=evidence.id,
        confirmed_by_admin_id=auth.id,
        confirmed_at=now,
        valid_until=data.valid_until,
        evidence_digest=hashlib.sha256(digest_source.encode()).hexdigest(),
    ))
    await _replace_grants(db, profile, data.grants)
    return profile


async def list_admin_voices(db: AsyncSession, org_id: UUID, auth: CurrentAdmin) -> list[VoiceProfile]:
    assert_org_write_access(auth, org_id)
    return list((await db.execute(
        select(VoiceProfile)
        .options(selectinload(VoiceProfile.grants))
        .where(VoiceProfile.organization_id == org_id, VoiceProfile.deleted_at.is_(None))
        .order_by(VoiceProfile.name)
    )).scalars().all())


async def update_voice(
    db: AsyncSession, voice_id: UUID, auth: CurrentAdmin, data: VoiceProfileUpdate,
) -> VoiceProfile:
    profile = await db.get(VoiceProfile, voice_id)
    if profile is None or profile.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    assert_org_write_access(auth, UUID(str(profile.organization_id)))
    if data.name is not None:
        profile.name = data.name
    if data.status is not None:
        profile.status = data.status
    if data.grants is not None:
        await _replace_grants(db, profile, data.grants)
    await db.flush()
    await db.refresh(profile)
    return profile


async def delete_voice(db: AsyncSession, voice_id: UUID, auth: CurrentAdmin) -> None:
    profile = await db.get(VoiceProfile, voice_id)
    if profile is None or profile.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    assert_org_write_access(auth, UUID(str(profile.organization_id)))
    now = datetime.now(UTC)
    profile.status = "pending_cleanup"
    profile.deleted_at = now
    for grant in profile.grants:
        grant.deleted_at = now
    authorization = (await db.execute(select(VoiceAuthorizationRecord).where(
        VoiceAuthorizationRecord.voice_profile_id == profile.id,
    ))).scalar_one_or_none()
    if authorization and authorization.revoked_at is None:
        authorization.revoked_at = now
    await db.flush()
