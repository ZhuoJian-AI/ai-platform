"""On-demand speech for owned assistant messages; no new Task or workspace file."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.auth.user_auth import current_user_for_user
from app.config import settings
from app.models.multimodal import MultimodalJob
from app.models.task import Task, TaskMessage
from app.models.user import User
from app.services import multimodal_audio_service as audio
from app.services import storage_gateway_service as storage
from app.services.speech_segments import SpeechSegmenter

PURPOSE = "message_read_aloud"


class MessageSpeechCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    message_id: UUID
    segment_index: int | None = Field(default=None, ge=0, le=63)
    expected_content_version: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def paired_segment_binding(self):
        if (self.segment_index is None) != (self.expected_content_version is None):
            raise ValueError("分句编号和正文版本必须同时提供")
        return self


def content_version(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def spoken_text(content: str) -> str:
    """Extract a bounded spoken excerpt, never reasoning, code, tables or URLs."""
    text = re.sub(r"<(think|thinking|analysis|reasoning)\b[^>]*>.*?(?:</\1\s*>|$)", "", content,
                  flags=re.I | re.S)
    text = re.sub(r"```.*?(?:```|$)|~~~.*?(?:~~~|$)", "", text, flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+|oss://\S+", "", text)
    lines = [line for line in text.splitlines() if "|" not in line and not line.lstrip().startswith(">")]
    text = re.sub(r"<[^>]*>|[`*_#]", "", "\n".join(lines))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise HTTPException(422, "该回复没有适合朗读的正文，请在聊天中查看详情")
    if len(text) > 600:
        excerpt = text[:600]
        boundary = max(excerpt.rfind(mark) for mark in "。！？.!?")
        text = excerpt[:boundary + 1] if boundary >= 100 else excerpt
        return f"以下为回复节选。{text} 更多内容请查看文字回复。"
    return text


async def owned_message(db, cu, task_id: UUID, message_id: UUID):
    message = (await db.execute(select(TaskMessage).join(Task, Task.id == TaskMessage.task_id).where(
        Task.id == task_id, TaskMessage.id == message_id,
        Task.organization_id == cu.organization_id, Task.user_id == UUID(cu.id),
        Task.deleted_at.is_(None), TaskMessage.role == "assistant",
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if message is None:
        raise HTTPException(404, "助手回复不存在或不属于当前用户")
    return message


def voice_version(voice) -> str:
    value = [str(voice.id), str(voice.updated_at), voice.provider_voice_id, voice.voice_type]
    return content_version(json.dumps(value, ensure_ascii=False))


def message_segments(content: str):
    return SpeechSegmenter().append(spoken_text(content), final=True)


async def plan(db, cu, task_id: UUID, message_id: UUID):
    await audio.require_multimodal_enabled(db, cu.organization_id)
    audio.require_permission(cu, "multimodal.speech.use")
    message = await owned_message(db, cu, task_id, message_id)
    return {"content_version": content_version(message.content),
            "segment_count": len(message_segments(message.content))}


async def create(db, cu, data: MessageSpeechCreate):
    await audio.require_multimodal_enabled(db, cu.organization_id)
    audio.require_permission(cu, "multimodal.speech.use")
    # Serialize same-user clicks, including concurrent tabs. Never cache across users.
    await db.execute(select(User.id).where(User.id == UUID(cu.id)).with_for_update())
    message = await owned_message(db, cu, data.task_id, data.message_id)
    text = spoken_text(message.content)
    if data.segment_index is not None:
        if content_version(message.content) != data.expected_content_version:
            raise HTTPException(409, "回复内容已变化，请朗读最新回复")
        segments = message_segments(message.content)
        if data.segment_index >= len(segments):
            raise HTTPException(422, "朗读分句不存在")
        text = segments[data.segment_index].text
    voices = await audio.list_visible_voices(db, cu)
    voice = next((item for item in voices if item.voice_type == "builtin"), None)
    if voice is None:
        raise HTTPException(409, "暂无获授权的标准音色，请联系管理员配置")
    deployment = await audio.model_gateway.resolve_deployment(
        db, cu.organization_id, "default", "text_to_speech", dept_id=cu.department_id,
    )
    if deployment is None:
        raise HTTPException(409, "暂无可用的语音朗读模型，请管理员检查部署")
    binding = {"task_id": str(data.task_id), "message_id": str(data.message_id),
               "content_version": content_version(message.content), "voice_version": voice_version(voice)}
    if data.segment_index is not None:
        binding["segment_index"] = data.segment_index
    cache_key = content_version(json.dumps(binding, sort_keys=True))
    existing = (await db.execute(select(MultimodalJob).where(
        MultimodalJob.organization_id == cu.organization_id, MultimodalJob.user_id == UUID(cu.id),
        MultimodalJob.params["purpose"].astext == PURPOSE,
        MultimodalJob.params["cache_key"].astext == cache_key,
        MultimodalJob.status.in_(["queued", "processing", "succeeded"]),
    ).order_by(MultimodalJob.created_at.desc()).limit(1))).scalar_one_or_none()
    if existing and not expired(existing) and (existing.status != "succeeded" or existing.output_file_ref):
        return existing
    expires = datetime.now(UTC) + timedelta(seconds=settings.workspace_upload_session_ttl_seconds)
    return await audio._create_job(
        db, cu, capability="text_to_speech", input_file_id=None, voice_profile_id=voice.id,
        params={**binding, "purpose": PURPOSE, "cache_key": cache_key, "text": text,
                "format": "mp3", "model": "default", "speed": 1.0,
                "cleanup_after": expires.isoformat()},
        idempotency_key=f"read-aloud:{cu.id}:{uuid4()}",
    )


def expired(job) -> bool:
    return datetime.now(UTC) >= datetime.fromisoformat(job.params["cleanup_after"])


async def authorize(db, cu, job):
    if str(job.user_id) != cu.id or str(job.organization_id) != str(cu.organization_id):
        raise HTTPException(404, "朗读任务不存在")
    await audio.require_multimodal_enabled(db, cu.organization_id)
    audio.require_permission(cu, "multimodal.speech.use")
    if expired(job):
        raise HTTPException(410, "临时朗读已过期，请重新点击朗读")
    message = await owned_message(db, cu, UUID(job.params["task_id"]), UUID(job.params["message_id"]))
    if content_version(message.content) != job.params["content_version"]:
        raise HTTPException(409, "回复内容已变化，请朗读最新回复")
    voice = await audio.get_visible_voice(db, cu, job.voice_profile_id)
    await db.refresh(voice)
    if voice.voice_type != "builtin" or voice_version(voice) != job.params["voice_version"]:
        raise HTTPException(409, "音色配置已变化，请重新点击朗读")


async def authorize_worker(db, job):
    # Refresh the effective role set after a potentially long provider request.
    user = await db.get(User, job.user_id, populate_existing=True)
    if user is None:
        raise HTTPException(403, "朗读用户已不可用")
    cu = await current_user_for_user(db, user)
    await authorize(db, cu, job)


async def cancel(db, cu, job_id: UUID):
    job = (await db.execute(select(MultimodalJob).where(
        MultimodalJob.id == job_id, MultimodalJob.organization_id == cu.organization_id,
        MultimodalJob.user_id == UUID(cu.id), MultimodalJob.params["purpose"].astext == PURPOSE,
    ).with_for_update())).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "朗读任务不存在")
    # Cancellation remains available after speech permission is revoked.
    if job.status in {"queued", "processing"}:
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
    await db.flush()


async def cleanup(db):
    jobs = list((await db.execute(select(MultimodalJob).where(
        MultimodalJob.params["purpose"].astext == PURPOSE,
        MultimodalJob.output_file_ref.is_not(None),
        MultimodalJob.status.in_(["succeeded", "failed", "cancelled"]),
    ).order_by(MultimodalJob.created_at).limit(30).with_for_update(skip_locked=True))).scalars())
    for job in jobs:
        if expired(job):
            await storage.delete_object(job.output_file_ref)
            job.output_file_ref = None
            job.result = {k: v for k, v in (job.result or {}).items() if k != "output_file_ref"}
    await db.flush()
