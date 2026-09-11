"""Short-lived recorder inputs owned by an existing audio job, never a workspace file."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.config import settings
from app.models.multimodal import MultimodalJob
from app.services import multimodal_audio_service as audio
from app.services import storage_gateway_service as storage

PURPOSE = "composer_recording"
MIME_SUFFIX = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}


class RecordingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size_bytes: int = Field(gt=0)
    content_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: UUID


async def create_upload(db, cu, data: RecordingCreate) -> dict:
    await audio.require_multimodal_enabled(db, cu.organization_id)
    audio.require_permission(cu, "multimodal.audio.transcribe")
    mime = data.content_type.split(";", 1)[0].strip().lower()
    if mime not in MIME_SUFFIX or data.size_bytes > settings.multimodal_audio_max_bytes:
        raise HTTPException(422, "录音格式不支持或大小超过平台限制")
    # Serializes duplicate requests for this user without relying on tool-call IDs.
    from app.models.user import User
    await db.execute(select(User.id).where(User.id == UUID(cu.id)).with_for_update())
    key = f"recording:{data.request_id}"
    existing = (await db.execute(select(MultimodalJob).where(
        MultimodalJob.organization_id == cu.organization_id,
        MultimodalJob.user_id == UUID(cu.id), MultimodalJob.idempotency_key == key,
    ))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "该录音已创建，请继续原任务或重新录音")
    job = await audio._create_job(
        db, cu, capability="speech_to_text", input_file_id=None, voice_profile_id=None,
        params={"purpose": PURPOSE, "upload_ready": False, "size_bytes": data.size_bytes,
                "sha256": data.sha256, "suffix": MIME_SUFFIX[mime], "model": "default", "language": "auto"},
        idempotency_key=key,
    )
    signed = await storage.sign_browser_upload(
        filename=f"recordings/{cu.organization_id}/{job.id}/{uuid4()}.{MIME_SUFFIX[mime]}",
        content_type=mime, size_bytes=data.size_bytes,
        max_allowed_bytes=settings.multimodal_audio_max_bytes, single_put=True,
    )
    # Wait beyond upload expiry before deleting: a cancelled in-flight PUT can finish late.
    expires = datetime.now(UTC) + timedelta(seconds=int(signed.get("expires_in", 300)) + 60)
    job.params = {**job.params, "input_ref": f"oss://{signed['object_key']}", "cleanup_after": expires.isoformat()}
    job.available_at = expires
    await db.flush()
    return {"job_id": str(job.id), "url": signed["url"], "fallback_url": signed.get("fallback_url"),
            "headers": signed["headers"]}


async def owned_recording(db, cu, job_id: UUID):
    job = (await db.execute(select(MultimodalJob).where(
        MultimodalJob.id == job_id, MultimodalJob.organization_id == cu.organization_id,
        MultimodalJob.user_id == UUID(cu.id),
    ).with_for_update())).scalar_one_or_none()
    if job is None or (job.params or {}).get("purpose") != PURPOSE:
        raise HTTPException(404, "录音任务不存在")
    return job


async def finalize(db, cu, job_id: UUID):
    await audio.require_multimodal_enabled(db, cu.organization_id)
    audio.require_permission(cu, "multimodal.audio.transcribe")
    job = await owned_recording(db, cu, job_id)
    if job.status == "cancelled":
        raise HTTPException(409, "录音已取消")
    if job.params.get("upload_ready"):
        return job
    if job.status != "queued" or datetime.now(UTC) >= job.available_at:
        raise HTTPException(409, "录音上传已过期，请重新录音")
    actual = await storage.inspect_object(job.params["input_ref"])
    if int(actual.get("size", -1)) != job.params["size_bytes"]:
        raise HTTPException(422, "录音上传不完整，请重新录音")
    job.params = {**job.params, "upload_ready": True}
    job.available_at = datetime.now(UTC)
    await db.flush()
    return job


async def cancel(db, cu, job_id: UUID):
    # Owner may cancel even after their ASR permission is revoked.
    job = await owned_recording(db, cu, job_id)
    if job.status in {"queued", "processing"}:
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
        job.result = {}
    await db.flush()


async def cleanup(db) -> None:
    jobs = list((await db.execute(select(MultimodalJob).where(
        MultimodalJob.status.in_(["succeeded", "failed", "cancelled"]),
        MultimodalJob.params["purpose"].astext == PURPOSE,
        MultimodalJob.params.has_key("input_ref"),
    ).order_by(MultimodalJob.created_at).limit(30).with_for_update(skip_locked=True))).scalars())
    for job in jobs:
        if datetime.now(UTC) < datetime.fromisoformat(job.params["cleanup_after"]):
            continue
        await storage.delete_object(job.params["input_ref"])
        job.params = {k: v for k, v in job.params.items() if k != "input_ref"}
    await db.flush()
