"""Crash-recoverable PostgreSQL worker for audio transcription and synthesis."""

from __future__ import annotations

import asyncio
import os
import socket
import tempfile
import time
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, or_, select

from app.config import settings
from app.database import async_session_factory
from app.models.multimodal import MultimodalJob, VoiceAuthorizationRecord, VoiceProfile
from app.models.workspace import WorkspaceFile
from app.services import model_gateway, storage_gateway_service

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


async def _run(*args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        raise model_gateway.GatewayError("invalid_audio")
    return stdout


async def _duration_ms(path: Path) -> int:
    raw = await _run(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    )
    try:
        return max(0, int(float(raw.decode().strip()) * 1000))
    except ValueError as exc:
        raise model_gateway.GatewayError("invalid_audio") from exc


async def _normalize_to_mp3(source: Path, target: Path) -> None:
    await _run(
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(target),
    )


async def _segment_mp3(source: Path, directory: Path) -> list[Path]:
    pattern = directory / "segment-%05d.mp3"
    await _run(
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-f", "segment", "-segment_time", "480", "-reset_timestamps", "1",
        "-c", "copy", str(pattern),
    )
    parts = sorted(directory.glob("segment-*.mp3"))
    if not parts:
        raise model_gateway.GatewayError("invalid_audio")
    if any(path.stat().st_size > 10 * 1024 * 1024 for path in parts):
        raise model_gateway.GatewayError("audio_segment_too_large")
    return parts


def _merge_transcripts(parts: list[str]) -> str:
    """Join ordered ASR chunks and remove a repeated boundary phrase."""
    merged = ""
    for current in parts:
        current = current.strip()
        if not current:
            continue
        if not merged:
            merged = current
            continue
        overlap = 0
        max_overlap = min(80, len(merged), len(current))
        for size in range(max_overlap, 5, -1):
            if merged[-size:] == current[:size]:
                overlap = size
                break
        merged = f"{merged}{current[overlap:]}"
    return merged


def _pcm16_to_wav(raw: bytes) -> bytes:
    with tempfile.SpooledTemporaryFile() as target:
        with wave.open(target, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(raw)
        target.seek(0)
        return target.read()


async def _claim_job() -> UUID | None:
    async with async_session_factory() as db:
        now = datetime.now(UTC)
        stale = now - timedelta(seconds=settings.multimodal_worker_lease_seconds)
        statement = (
            select(MultimodalJob)
            .where(
                or_(
                    (MultimodalJob.status == "queued") & (MultimodalJob.available_at <= now),
                    (MultimodalJob.status == "processing") & (MultimodalJob.locked_at < stale),
                ),
                MultimodalJob.attempts < MultimodalJob.max_attempts,
            )
            .order_by(MultimodalJob.available_at, MultimodalJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = (await db.execute(statement)).scalar_one_or_none()
        if job is None:
            return None
        job.status = "processing"
        job.locked_at = now
        job.locked_by = WORKER_ID
        job.attempts += 1
        await db.commit()
        return job.id


async def _cleanup_voice_profile() -> bool:
    """Remove generated/cache objects for one revoked voice profile.

    Source samples and authorization evidence remain governed by workspace
    lifecycle rules so an audit record never points at a silently hard-deleted
    file.
    """
    async with async_session_factory() as db:
        profile = (await db.execute(
            select(VoiceProfile)
            .where(VoiceProfile.status == "pending_cleanup")
            .order_by(VoiceProfile.updated_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )).scalar_one_or_none()
        if profile is None:
            return False
        jobs = list((await db.execute(select(MultimodalJob).where(
            MultimodalJob.voice_profile_id == profile.id,
            MultimodalJob.output_file_ref.is_not(None),
        ))).scalars().all())
        for job in jobs:
            assert job.output_file_ref is not None
            await storage_gateway_service.delete_object(job.output_file_ref)
            job.output_file_ref = None
            result = dict(job.result or {})
            result.pop("output_file_ref", None)
            result["output_deleted"] = True
            job.result = result
        profile.status = "disabled"
        profile.config = {
            **dict(profile.config or {}),
            "cleanup_completed_at": datetime.now(UTC).isoformat(),
            "workspace_source_files_retained": True,
        }
        await db.commit()
        return True


async def _assert_daily_quota(db, job: MultimodalJob) -> None:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used_ms = int((await db.scalar(select(func.coalesce(func.sum(MultimodalJob.audio_duration_ms), 0)).where(
        MultimodalJob.organization_id == job.organization_id,
        MultimodalJob.status == "succeeded",
        MultimodalJob.finished_at >= today,
    ))) or 0)
    if used_ms >= settings.multimodal_daily_audio_seconds * 1000:
        raise model_gateway.GatewayError("organization_audio_quota_exceeded")


async def _load_input(db, job: MultimodalJob, directory: Path) -> tuple[WorkspaceFile, Path]:
    if job.input_file_id is None:
        raise model_gateway.GatewayError("missing_audio_input")
    file = await db.get(WorkspaceFile, job.input_file_id)
    if file is None or not file.content_ref or file.deleted_at is not None:
        raise model_gateway.GatewayError("audio_input_unavailable")
    suffix = Path(file.path).suffix.lower() or ".bin"
    target = directory / f"input{suffix}"
    await storage_gateway_service.download_to_path(
        file.content_ref, target, max_bytes=settings.multimodal_audio_max_bytes,
    )
    return file, target


async def _transcribe(db, job: MultimodalJob, directory: Path) -> dict:
    _, source = await _load_input(db, job, directory)
    normalized = directory / "normalized.mp3"
    await _normalize_to_mp3(source, normalized)
    duration_ms = await _duration_ms(normalized)
    parts = await _segment_mp3(normalized, directory)
    transcripts: list[str] = []
    segment_results: list[dict] = []
    total_usage: dict[str, int] = {}
    deployment_id = None
    model = None
    for index, part in enumerate(parts):
        result = await model_gateway.transcribe_audio(
            db,
            UUID(str(job.organization_id)),
            part.read_bytes(),
            audio_format="mp3",
            language=str(job.params.get("language") or "auto"),
            model_alias=str(job.params.get("model") or "default"),
            dept_id=job.department_id,
        )
        transcripts.append(result["text"])
        segment_results.append({"index": index, "text": result["text"]})
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, int):
                total_usage[key] = total_usage.get(key, 0) + value
        deployment_id = result["deployment_id"]
        model = result["model"]
    job.audio_duration_ms = duration_ms
    job.deployment_id = UUID(deployment_id) if deployment_id else None
    return {
        "result": {"text": _merge_transcripts(transcripts), "segments": segment_results, "model": model},
        "usage": total_usage,
    }


async def _synthesize(db, job: MultimodalJob, directory: Path) -> dict:
    profile = await db.get(VoiceProfile, job.voice_profile_id) if job.voice_profile_id else None
    if profile is None or profile.status != "active" or profile.deleted_at is not None:
        raise model_gateway.GatewayError("voice_profile_unavailable")
    clone_audio = None
    clone_format = "wav"
    if profile.voice_type == "cloned":
        authorization = (await db.execute(select(VoiceAuthorizationRecord).where(
            VoiceAuthorizationRecord.voice_profile_id == profile.id,
            VoiceAuthorizationRecord.revoked_at.is_(None),
            VoiceAuthorizationRecord.valid_until > datetime.now(UTC),
        ))).scalar_one_or_none()
        if authorization is None:
            raise model_gateway.GatewayError("voice_authorization_invalid")
        _, clone_source = await _load_input(db, job, directory)
        normalized = directory / "clone.mp3"
        await _normalize_to_mp3(clone_source, normalized)
        clone_audio = normalized.read_bytes()
        clone_format = "mp3"
    requested_format = str(job.params.get("format") or "wav")
    result = await model_gateway.synthesize_audio(
        db,
        UUID(str(job.organization_id)),
        text=str(job.params.get("text") or ""),
        voice=profile.provider_voice_id,
        audio_format=requested_format,
        style=job.params.get("style"),
        speed=float(job.params.get("speed") or 1.0),
        design_prompt=profile.design_prompt if profile.voice_type == "designed" else None,
        clone_audio=clone_audio,
        clone_format=clone_format,
        model_alias=str(job.params.get("model") or "default"),
        dept_id=job.department_id,
    )
    raw = result["audio"]
    final_format = requested_format
    if requested_format in {"pcm", "pcm16"}:
        raw = _pcm16_to_wav(raw)
        final_format = "wav"
    output_path = directory / f"output.{final_format}"
    output_path.write_bytes(raw)
    job.audio_duration_ms = await _duration_ms(output_path)
    content_type = "audio/mpeg" if final_format == "mp3" else "audio/wav"
    output_ref = await storage_gateway_service.upload_bytes(
        raw,
        filename=f"multimodal/{job.organization_id}/{job.id}.{final_format}",
        content_type=content_type,
    )
    job.output_file_ref = output_ref
    job.deployment_id = UUID(result["deployment_id"])
    return {
        "result": {
            "output_file_ref": output_ref,
            "format": final_format,
            "model": result["model"],
            "provider_voice_id": result.get("provider_voice_id"),
        },
        "usage": result.get("usage") or {},
    }


async def _process(job_id: UUID) -> None:
    started = time.monotonic()
    async with async_session_factory() as db:
        job = await db.get(MultimodalJob, job_id)
        if job is None or job.status != "processing" or job.locked_by != WORKER_ID:
            return
        try:
            await _assert_daily_quota(db, job)
            with tempfile.TemporaryDirectory(prefix="zhuojian-audio-") as raw_dir:
                directory = Path(raw_dir)
                if job.capability == "speech_to_text":
                    payload = await _transcribe(db, job, directory)
                elif job.capability in {"text_to_speech", "voice_design", "voice_clone"}:
                    payload = await _synthesize(db, job, directory)
                else:
                    raise model_gateway.GatewayError("unsupported_multimodal_job")
            job.result = payload["result"]
            job.usage = payload["usage"]
            job.status = "succeeded"
            job.finished_at = datetime.now(UTC)
            job.error_category = None
            job.error_detail = None
        except Exception as exc:
            category = model_gateway.classify_gateway_error(exc)
            job.error_category = category
            job.error_detail = "Audio processing failed"
            job.locked_at = None
            job.locked_by = None
            retryable = model_gateway.is_retryable_gateway_error(exc)
            if retryable and job.attempts < job.max_attempts:
                job.status = "queued"
                retry_after = getattr(exc, "retry_after_seconds", None)
                delay = retry_after if retry_after is not None else min(60, 2 ** job.attempts)
                job.available_at = datetime.now(UTC) + timedelta(seconds=max(1, min(300, delay)))
            else:
                job.status = "failed"
                job.finished_at = datetime.now(UTC)
        finally:
            job.latency_ms = int((time.monotonic() - started) * 1000)
            await db.commit()


async def run_forever() -> None:
    while True:
        try:
            if await _cleanup_voice_profile():
                continue
        except Exception:
            # Leave the profile in pending_cleanup so a later loop retries.
            await asyncio.sleep(settings.multimodal_worker_poll_seconds)
            continue
        job_id = await _claim_job()
        if job_id is None:
            await asyncio.sleep(settings.multimodal_worker_poll_seconds)
            continue
        await _process(job_id)


if __name__ == "__main__":
    asyncio.run(run_forever())
