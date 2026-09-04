"""Capability-aware model gateway used by Agent Runtime and RAG.

The gateway owns provider/deployment selection and wire-protocol adaptation.  It
does not plan agent work, execute Skills, or persist workspace files.  Existing
providers without explicit deployments remain available through the legacy
client so the rollout is backwards compatible.
"""

from __future__ import annotations

import base64
import io
import re
import wave
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm_client as legacy_client
from app.config import settings
from app.models.llm_provider import LlmProvider, ModelDeployment
from app.models.organization import Organization
from app.services.ai_quota_service import (
    QuotaBackendUnavailableError,
    QuotaConfigurationError,
    QuotaExceededError,
    QuotaReservation,
    monotonic_request_id,
    reserve_ai_quota,
    settle_ai_quota,
)
from app.services.llm_provider_service import effective_provider, get_decrypted_api_key

LlmResult = legacy_client.LlmResult
ImageGenerationResult = legacy_client.ImageGenerationResult

_SCOPE_RANK = {"team": 3, "department": 2, "organization": 1}
_ROUTABLE_STATES = {"verified", "legacy"}
_RETRYABLE_MARKERS = (" 429", " 500", " 502", " 503", " 504", "timeout", "timed out", "connect")
_TEST_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKklEQVR4nGNQqLhAU8QwasGoBaMWjFowasGoBaMWjFowasGoBaMWDBULAEuXoEzmj87AAAAAAElFTkSuQmCC"
)
_AUDIO_INPUT_LIMIT_BYTES = 10 * 1024 * 1024


class GatewayError(RuntimeError):
    """A credential-safe upstream failure category."""

    def __init__(self, category: str, *, retry_after_seconds: float | None = None):
        self.category = category
        self.retry_after_seconds = retry_after_seconds
        super().__init__(category)


async def _reserve_gateway_quota(
    db: AsyncSession,
    org_id: UUID,
    *,
    payload: Any,
    max_output_tokens: int = 0,
    input_token_upper_bound: int | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    supports_token_metering: bool = True,
    operation: str,
    provider_id: str | UUID | None = None,
    request_id: str | None = None,
) -> QuotaReservation:
    try:
        return await reserve_ai_quota(
            db,
            org_id,
            payload=payload,
            max_output_tokens=max_output_tokens,
            input_token_upper_bound=input_token_upper_bound,
            department_id=dept_id,
            team_id=team_id,
            request_id=request_id or monotonic_request_id(operation),
            supports_token_metering=supports_token_metering,
            provider_id=provider_id,
            operation=operation,
        )
    except QuotaExceededError as exc:
        raise GatewayError(
            "platform_quota_exceeded",
            retry_after_seconds=exc.retry_after_seconds,
        ) from exc
    except QuotaBackendUnavailableError as exc:
        raise GatewayError("quota_backend_unavailable") from exc
    except QuotaConfigurationError as exc:
        raise GatewayError("quota_configuration_error") from exc


async def _metered_result(
    db: AsyncSession,
    reservation: QuotaReservation,
    operation: Callable[[], Awaitable[Any]],
    usage: Callable[[Any], dict[str, Any] | None],
) -> Any:
    try:
        result = await operation()
    except BaseException:
        await settle_ai_quota(reservation, None, db=db, outcome="failed")
        raise
    await settle_ai_quota(reservation, usage(result), db=db, outcome="completed")
    return result


def _bounded_max_tokens(value: int | None) -> int:
    try:
        maximum = (
            settings.ai_quota_default_max_output_tokens
            if value is None
            else int(value)
        )
    except (TypeError, ValueError) as exc:
        raise GatewayError("quota_configuration_error") from exc
    if maximum < 0:
        raise GatewayError("quota_configuration_error")
    return maximum


def _openai_headers(api_key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {api_key}", "content-type": "application/json"}


async def _post_chat_json(
    provider: LlmProvider,
    deployment: ModelDeployment,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Call one chat-completions deployment without leaking provider payloads."""
    api_key = await get_decrypted_api_key(provider)
    path = _safe_endpoint_path(deployment.endpoint_path or "/chat/completions", "Chat API")
    try:
        async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
            response = await client.post(
                f"{provider.base_url.rstrip('/')}{path}",
                headers=_openai_headers(api_key),
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise GatewayError("network_timeout") from exc
    except httpx.NetworkError as exc:
        raise GatewayError("network_failure") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise GatewayError("invalid_provider_response") from exc
    if response.status_code >= 400:
        retry_after = response.headers.get("retry-after")
        try:
            retry_after_seconds = float(retry_after) if retry_after else None
        except ValueError:
            retry_after_seconds = None
        raise GatewayError(
            _upstream_error_category(response.status_code, data),
            retry_after_seconds=retry_after_seconds,
        )
    return data


def _message_content(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise GatewayError("invalid_provider_response")
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise GatewayError("invalid_provider_response")
    return message, data.get("usage") or {}


async def _transcribe_audio_unmetered(
    db: AsyncSession,
    org_id: UUID,
    audio: bytes,
    *,
    audio_format: str,
    language: str = "auto",
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> dict[str, Any]:
    """Transcribe MP3/WAV bytes through a same-capability deployment only."""
    normalized_format = audio_format.lower().removeprefix("audio/")
    if normalized_format not in {"mp3", "mpeg", "wav", "wave", "x-wav"}:
        raise GatewayError("unsupported_audio_format")
    if len(audio) > _AUDIO_INPUT_LIMIT_BYTES:
        raise GatewayError("audio_segment_too_large")
    resolved = await resolve_deployment(
        db, org_id, model_alias, "speech_to_text", dept_id=dept_id, team_id=team_id,
    )
    if not resolved:
        raise GatewayError("capability_not_configured")
    provider, deployment = resolved
    if deployment.adapter != "openai_audio_transcription_chat":
        raise GatewayError("capability_mismatch")
    wire_format = "mp3" if normalized_format in {"mp3", "mpeg"} else "wav"
    mime_type = "audio/mpeg" if wire_format == "mp3" else "audio/wav"
    encoded = base64.b64encode(audio).decode("ascii")
    body = {
        "model": deployment.model_id,
        "messages": [{
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {"data": f"data:{mime_type};base64,{encoded}"},
            }],
        }],
        "asr_options": {"language": language},
        "stream": False,
        "max_tokens": settings.ai_quota_default_max_output_tokens,
    }
    data = await _post_chat_json(effective_provider(provider, deployment), deployment, body)
    message, usage = _message_content(data)
    content = message.get("content")
    if not isinstance(content, str):
        raise GatewayError("invalid_provider_response")
    return {
        "text": content,
        "segments": message.get("segments") or [],
        "usage": usage,
        "deployment_id": str(deployment.id),
        "model": deployment.model_id,
    }


def _combined_usage(results: list[dict[str, Any]]) -> dict[str, int] | None:
    """Combine provider counters from one internally segmented operation."""

    combined: dict[str, int] = {}
    for result in results:
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, int) and not isinstance(value, bool):
                combined[key] = combined.get(key, 0) + value
    return combined or None


async def transcribe_audio_segments(
    db: AsyncSession,
    org_id: UUID,
    audio_segments: Iterable[bytes],
    *,
    audio_format: str,
    language: str = "auto",
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Transcribe every internal segment under one logical quota reservation."""

    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={"capability": "speech_to_text", "model": model_alias},
        dept_id=dept_id,
        team_id=team_id,
        supports_token_metering=False,
        operation="speech-to-text",
        request_id=request_id,
    )

    async def invoke() -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for audio in audio_segments:
            results.append(
                await _transcribe_audio_unmetered(
                    db,
                    org_id,
                    audio,
                    audio_format=audio_format,
                    language=language,
                    model_alias=model_alias,
                    dept_id=dept_id,
                    team_id=team_id,
                )
            )
        if not results:
            raise GatewayError("missing_audio_input")
        return results

    return await _metered_result(db, reservation, invoke, _combined_usage)


async def transcribe_audio(
    db: AsyncSession,
    org_id: UUID,
    audio: bytes,
    *,
    audio_format: str,
    language: str = "auto",
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    results = await transcribe_audio_segments(
        db,
        org_id,
        (audio,),
        audio_format=audio_format,
        language=language,
        model_alias=model_alias,
        dept_id=dept_id,
        team_id=team_id,
        request_id=request_id,
    )
    return results[0]


async def _understand_audio_unmetered(
    db: AsyncSession,
    org_id: UUID,
    audio_url: str,
    question: str,
    *,
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> LlmResult:
    """Ask a question about an object-scoped, short-lived audio URL."""
    resolved = await resolve_deployment(
        db, org_id, model_alias, "audio_understanding", dept_id=dept_id, team_id=team_id,
    )
    if not resolved:
        raise GatewayError("capability_not_configured")
    provider, deployment = resolved
    if deployment.adapter != "openai_chat_completions":
        raise GatewayError("capability_mismatch")
    result = await _chat_with_deployment(
        db,
        org_id,
        provider,
        deployment,
        [{
            "role": "user",
            "content": [
                {"type": "input_audio", "input_audio": {"data": audio_url}},
                {"type": "text", "text": question},
            ],
        }],
        max_tokens=settings.ai_quota_default_max_output_tokens,
    )
    return result


async def understand_audio(
    db: AsyncSession,
    org_id: UUID,
    audio_url: str,
    question: str,
    *,
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    audio_size_bytes: int | None = None,
) -> LlmResult:
    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={"capability": "audio_understanding", "question": question},
        dept_id=dept_id,
        team_id=team_id,
        supports_token_metering=False,
        operation="audio-understanding",
    )

    async def invoke() -> LlmResult:
        return await _understand_audio_unmetered(
            db,
            org_id,
            audio_url,
            question,
            model_alias=model_alias,
            dept_id=dept_id,
            team_id=team_id,
        )

    return await _metered_result(db, reservation, invoke, lambda result: result.usage)


async def _stream_understand_audio_unmetered(
    db: AsyncSession,
    org_id: UUID,
    audio_url: str,
    question: str,
    *,
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> AsyncIterator[tuple[str, Any, Any]]:
    """Stream audio understanding without falling back to a chat-only model."""
    resolved = await resolve_deployment(
        db, org_id, model_alias, "audio_understanding", dept_id=dept_id, team_id=team_id,
    )
    if not resolved:
        raise GatewayError("capability_not_configured")
    provider, deployment = resolved
    if deployment.adapter != "openai_chat_completions":
        raise GatewayError("capability_mismatch")
    messages = [{
        "role": "user",
        "content": [
            {"type": "input_audio", "input_audio": {"data": audio_url}},
            {"type": "text", "text": question},
        ],
    }]
    async for event in legacy_client.stream_chat(
        db,
        org_id,
        deployment.model_id,
        messages,
        provider_override=effective_provider(provider, deployment),
        model_override=deployment.model_id,
        max_tokens=settings.ai_quota_default_max_output_tokens,
    ):
        yield event


async def stream_understand_audio(
    db: AsyncSession,
    org_id: UUID,
    audio_url: str,
    question: str,
    *,
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    audio_size_bytes: int | None = None,
) -> AsyncIterator[tuple[str, Any, Any]]:
    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={"capability": "audio_understanding", "question": question},
        dept_id=dept_id,
        team_id=team_id,
        supports_token_metering=False,
        operation="stream-audio-understanding",
    )
    usage: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
    completed = False
    try:
        async for event in _stream_understand_audio_unmetered(
            db,
            org_id,
            audio_url,
            question,
            model_alias=model_alias,
            dept_id=dept_id,
            team_id=team_id,
        ):
            if event[0] == "usage" and isinstance(event[2], dict):
                if event[2].get("input_tokens") is not None:
                    usage["input_tokens"] = int(event[2]["input_tokens"])
                if event[2].get("output_tokens") is not None:
                    usage["output_tokens"] = int(event[2]["output_tokens"])
            yield event
        completed = True
    finally:
        await settle_ai_quota(
            reservation,
            usage if completed else None,
            db=db,
            outcome="completed" if completed else "disconnected",
        )


async def _synthesize_audio_unmetered(
    db: AsyncSession,
    org_id: UUID,
    *,
    text: str,
    voice: str | None = None,
    audio_format: str = "wav",
    style: str | None = None,
    speed: float = 1.0,
    design_prompt: str | None = None,
    clone_audio: bytes | None = None,
    clone_format: str = "wav",
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> dict[str, Any]:
    capability = "voice_clone" if clone_audio is not None else "voice_design" if design_prompt else "text_to_speech"
    resolved = await resolve_deployment(
        db, org_id, model_alias, capability, dept_id=dept_id, team_id=team_id,
    )
    if not resolved:
        raise GatewayError("capability_not_configured")
    provider, deployment = resolved
    if deployment.adapter != "openai_audio_synthesis_chat":
        raise GatewayError("capability_mismatch")
    if audio_format not in {"wav", "mp3", "pcm", "pcm16"}:
        raise GatewayError("unsupported_audio_format")
    instructions: list[str] = []
    if design_prompt:
        instructions.append(design_prompt)
    if style:
        instructions.append(style)
    if speed != 1.0:
        instructions.append(f"请以 {speed:.2f} 倍的相对语速朗读。")
    if clone_audio is not None:
        if clone_format not in {"mp3", "wav"} or len(clone_audio) > _AUDIO_INPUT_LIMIT_BYTES:
            raise GatewayError("invalid_voice_clone_sample")
        encoded = base64.b64encode(clone_audio).decode("ascii")
        mime_type = "audio/mpeg" if clone_format == "mp3" else "audio/wav"
        voice = f"data:{mime_type};base64,{encoded}"
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "\n".join(instructions)},
        {"role": "assistant", "content": text},
    ]
    audio: dict[str, Any] = {"format": audio_format}
    if voice:
        audio["voice"] = voice
    if design_prompt:
        audio["optimize_text_preview"] = False
    body = {
        "model": deployment.model_id,
        "messages": messages,
        "audio": audio,
        "stream": False,
        "max_tokens": settings.ai_quota_default_max_output_tokens,
    }
    data = await _post_chat_json(effective_provider(provider, deployment), deployment, body)
    message, usage = _message_content(data)
    audio_payload = message.get("audio") or {}
    encoded_audio = audio_payload.get("data")
    if not isinstance(encoded_audio, str):
        raise GatewayError("invalid_provider_response")
    try:
        raw = base64.b64decode(encoded_audio, validate=True)
    except (ValueError, TypeError) as exc:
        raise GatewayError("invalid_provider_response") from exc
    if not raw:
        raise GatewayError("invalid_provider_response")
    return {
        "audio": raw,
        "format": audio_format,
        "usage": usage,
        "deployment_id": str(deployment.id),
        "model": deployment.model_id,
        "provider_voice_id": audio_payload.get("voice"),
    }


async def synthesize_audio(
    db: AsyncSession,
    org_id: UUID,
    *,
    text: str,
    voice: str | None = None,
    audio_format: str = "wav",
    style: str | None = None,
    speed: float = 1.0,
    design_prompt: str | None = None,
    clone_audio: bytes | None = None,
    clone_format: str = "wav",
    model_alias: str = "default",
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={
            "capability": "text_to_speech",
            "text": text,
            "style": style,
            "design_prompt": design_prompt,
        },
        dept_id=dept_id,
        team_id=team_id,
        supports_token_metering=False,
        operation="speech-synthesis",
        request_id=request_id,
    )

    async def invoke() -> dict[str, Any]:
        return await _synthesize_audio_unmetered(
            db,
            org_id,
            text=text,
            voice=voice,
            audio_format=audio_format,
            style=style,
            speed=speed,
            design_prompt=design_prompt,
            clone_audio=clone_audio,
            clone_format=clone_format,
            model_alias=model_alias,
            dept_id=dept_id,
            team_id=team_id,
        )

    return await _metered_result(db, reservation, invoke, lambda result: result.get("usage"))


def _upstream_error_category(status_code: int, payload: Any = None) -> str:
    lowered = str(payload or "").lower()[:4000]
    # Bailian returns HTTP 403 when a model's free tier is exhausted. Inspect
    # stable provider error fields before treating every 403 as a bad key, or
    # administrators are sent to rotate a credential that is working correctly.
    if any(
        marker in lowered
        for marker in (
            "quota",
            "balance",
            "insufficient",
            "free tier",
            "freetier",
            "余额",
            "配额",
        )
    ):
        return "quota_or_rate_limit"
    if any(marker in lowered for marker in ("model_not_found", "model not found", "unknown model")):
        return "model_not_found"
    if status_code in {401, 403}:
        return "invalid_credentials_or_permission"
    if status_code == 404:
        return "model_not_found"
    if status_code == 429:
        return "quota_or_rate_limit"
    if status_code >= 500:
        return "provider_service_unavailable"
    if status_code == 400 and any(
        marker in lowered
        for marker in ("unsupported", "capability", "dimension", "image", "vision", "size")
    ):
        return "capability_mismatch"
    return "provider_rejected_request"


def classify_gateway_error(exc: Exception) -> str:
    """Return a stable category without exposing an upstream response body."""
    if isinstance(exc, GatewayError):
        return exc.category
    if isinstance(exc, httpx.TimeoutException):
        return "network_timeout"
    if isinstance(exc, httpx.NetworkError):
        return "network_failure"
    lowered = str(exc).lower()
    if any(marker in lowered for marker in ("401", "403", "unauthorized", "forbidden")):
        return "invalid_credentials_or_permission"
    if any(marker in lowered for marker in ("429", "quota", "balance", "insufficient")):
        return "quota_or_rate_limit"
    if "404" in lowered or "model not found" in lowered:
        return "model_not_found"
    if any(marker in lowered for marker in ("timeout", "timed out")):
        return "network_timeout"
    if any(marker in lowered for marker in ("connect", "network", "dns")):
        return "network_failure"
    if any(marker in lowered for marker in ("500", "502", "503", "504")):
        return "provider_service_unavailable"
    return "capability_test_failed"


def _safe_endpoint_path(path: str, label: str) -> str:
    if not path.startswith("/") or "://" in path or ".." in path:
        raise GatewayError("invalid_endpoint_configuration")
    return path


def _normalize_bailian_image_size(value: str) -> str:
    """Convert the platform's canonical ``WIDTHxHEIGHT`` into Bailian ``WIDTH*HEIGHT``."""
    match = re.fullmatch(r"\s*(\d+)\s*[xX*]\s*(\d+)\s*", value)
    if not match:
        raise GatewayError("invalid_image_size")
    width, height = (int(match.group(1)), int(match.group(2)))
    if width <= 0 or height <= 0:
        raise GatewayError("invalid_image_size")
    return f"{width}*{height}"


def _scope_clause(dept_id: str | UUID | None, team_id: str | UUID | None):
    branches = [LlmProvider.scope_type == "organization"]
    if dept_id:
        branches.append(
            (LlmProvider.scope_type == "department")
            & (LlmProvider.department_id == UUID(str(dept_id)))
        )
    if team_id:
        branches.append(
            (LlmProvider.scope_type == "team")
            & (LlmProvider.team_id == UUID(str(team_id)))
        )
    return or_(*branches)


async def candidate_deployments(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    capability: str,
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    include_unverified: bool = False,
) -> list[tuple[LlmProvider, ModelDeployment]]:
    """Return scoped deployments ordered by inheritance, route priority and provider priority."""
    statement = (
        select(LlmProvider, ModelDeployment)
        .join(ModelDeployment, ModelDeployment.provider_id == LlmProvider.id)
        .where(
            LlmProvider.organization_id == org_id,
            LlmProvider.is_active.is_(True),
            LlmProvider.deleted_at.is_(None),
            LlmProvider.health_status != "down",
            ModelDeployment.is_active.is_(True),
            ModelDeployment.deleted_at.is_(None),
            _scope_clause(dept_id, team_id),
        )
    )
    if model_alias and model_alias != "default":
        statement = statement.where(ModelDeployment.model_id == model_alias)
    rows = list((await db.execute(statement)).all())
    organization = await db.get(Organization, org_id)
    allow_new_gateway = bool(
        organization
        and settings.model_gateway_enabled_for(
            organization.slug, organization_id=organization.id
        )
    )
    candidates = [
        (provider, deployment)
        for provider, deployment in rows
        if capability in (deployment.capabilities or [])
        and (include_unverified or deployment.verification_status in _ROUTABLE_STATES)
        and (allow_new_gateway or deployment.verification_status == "legacy" or include_unverified)
    ]
    candidates.sort(
        key=lambda item: (
            _SCOPE_RANK.get(item[0].scope_type, 0),
            item[1].routing_priority,
            item[0].priority,
        ),
        reverse=True,
    )
    return candidates


async def resolve_deployment(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    capability: str,
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    include_unverified: bool = False,
) -> tuple[LlmProvider, ModelDeployment] | None:
    candidates = await candidate_deployments(
        db, org_id, model_alias, capability,
        dept_id=dept_id, team_id=team_id, include_unverified=include_unverified,
    )
    return candidates[0] if candidates else None


async def _assert_legacy_fallback_allowed(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    capability: str,
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> None:
    """Block the legacy router from bypassing gateway verification/rollout gates."""
    declared = await candidate_deployments(
        db,
        org_id,
        model_alias,
        capability,
        dept_id=dept_id,
        team_id=team_id,
        include_unverified=True,
    )
    if declared:
        if any(deployment.verification_status in _ROUTABLE_STATES for _, deployment in declared):
            raise GatewayError("model_gateway_not_enabled")
        raise GatewayError("deployment_not_verified")


async def resolve_provider_model(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    *,
    for_embeddings: bool = False,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> tuple[str, str]:
    capability = "embedding" if for_embeddings else "chat"
    resolved = await resolve_deployment(
        db, org_id, model_alias, capability, dept_id=dept_id, team_id=team_id,
    )
    if resolved:
        provider, deployment = resolved
        return str(provider.id), deployment.model_id
    await _assert_legacy_fallback_allowed(
        db, org_id, model_alias, capability, dept_id=dept_id, team_id=team_id,
    )
    return await legacy_client.resolve_provider_model(
        db, org_id, model_alias, for_embeddings=for_embeddings,
        dept_id=dept_id, team_id=team_id,
    )


async def resolve_provider(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> tuple[LlmProvider, str]:
    resolved = await resolve_deployment(
        db, org_id, model_alias, "chat", dept_id=dept_id, team_id=team_id,
    )
    if resolved:
        provider, deployment = resolved
        return effective_provider(provider, deployment), deployment.model_id
    await _assert_legacy_fallback_allowed(
        db, org_id, model_alias, "chat", dept_id=dept_id, team_id=team_id,
    )
    return await legacy_client.resolve_provider(
        db, org_id, model_alias, dept_id=dept_id, team_id=team_id,
    )


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, GatewayError):
        return exc.category in {
            "quota_or_rate_limit",
            "network_timeout",
            "network_failure",
            "provider_service_unavailable",
        }
    lowered = str(exc).lower()
    return any(marker in lowered for marker in _RETRYABLE_MARKERS)


def is_retryable_gateway_error(exc: Exception) -> bool:
    """Public retry policy shared by durable workers."""
    return _retryable(exc)


def _responses_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    converted: list[dict] = []
    for tool in tools:
        function = tool.get("function") or {}
        converted.append({
            "type": "function",
            "name": function.get("name", ""),
            "description": function.get("description", ""),
            "parameters": function.get("parameters") or {"type": "object", "properties": {}},
        })
    return converted


def _responses_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    converted: list[dict] = []
    for part in content:
        if part.get("type") == "text":
            converted.append({"type": "input_text", "text": part.get("text", "")})
        elif part.get("type") == "image_url":
            image_url = part.get("image_url") or {}
            converted.append({"type": "input_image", "image_url": image_url.get("url", "")})
        else:
            converted.append(part)
    return converted


def _responses_input(messages: list[dict]) -> list[dict]:
    items: list[dict] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": message.get("tool_call_id", ""),
                "output": str(message.get("content", "")),
            })
            continue
        if role == "assistant" and message.get("tool_calls"):
            if message.get("content"):
                items.append({"role": "assistant", "content": message["content"]})
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                items.append({
                    "type": "function_call",
                    "call_id": call.get("id", ""),
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments", "{}"),
                })
            continue
        items.append({"role": role, "content": _responses_content(message.get("content", ""))})
    return items


async def _responses_chat(
    provider: LlmProvider,
    deployment: ModelDeployment,
    messages: list[dict],
    *,
    system_prompt: str,
    temperature: float | None,
    max_tokens: int | None,
    tools: list[dict] | None,
) -> LlmResult:
    api_key = await get_decrypted_api_key(provider)
    path = _safe_endpoint_path(deployment.endpoint_path or "/responses", "Responses API")
    body: dict[str, Any] = {
        "model": deployment.model_id,
        "input": _responses_input(messages),
    }
    if system_prompt:
        body["instructions"] = system_prompt
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_output_tokens"] = max_tokens
    response_tools = _responses_tools(tools)
    if response_tools:
        body["tools"] = response_tools
    async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
        response = await client.post(
            f"{provider.base_url.rstrip('/')}{path}",
            headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json=body,
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise GatewayError("invalid_provider_response") from exc
    if response.status_code >= 400:
        raise GatewayError(_upstream_error_category(response.status_code, data))
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") in {"output_text", "text"}:
                    text_parts.append(part.get("text", ""))
        elif item.get("type") == "function_call":
            tool_calls.append({
                "id": item.get("call_id") or item.get("id", ""),
                "name": item.get("name", ""),
                "arguments": item.get("arguments", "{}"),
            })
    usage = data.get("usage") or {}
    return LlmResult(
        content="".join(text_parts),
        tool_calls=tool_calls,
        usage={
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        },
        provider_id=str(provider.id),
        model_served=deployment.model_id,
        reasoning_content=data.get("reasoning_content"),
    )


async def _chat_with_deployment(
    db: AsyncSession,
    org_id: UUID,
    provider: LlmProvider,
    deployment: ModelDeployment,
    messages: list[dict],
    **kwargs: Any,
) -> LlmResult:
    if deployment.adapter == "openai_responses":
        return await _responses_chat(
            provider, deployment, messages,
            system_prompt=kwargs.get("system_prompt", ""),
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
            tools=kwargs.get("tools"),
        )
    return await legacy_client.chat(
        db, org_id, deployment.model_id, messages,
        system_prompt=kwargs.get("system_prompt", ""),
        temperature=kwargs.get("temperature"),
        max_tokens=kwargs.get("max_tokens"),
        tools=kwargs.get("tools"),
        provider_override=effective_provider(provider, deployment),
        model_override=deployment.model_id,
    )


async def _chat_unmetered(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    messages: list[dict],
    *,
    system_prompt: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    provider_override: LlmProvider | None = None,
    model_override: str | None = None,
) -> LlmResult:
    if provider_override is not None:
        deployment_id = str((provider_override.config or {}).get("_gateway_deployment_id") or "").strip()
        if deployment_id:
            deployment = await db.get(ModelDeployment, UUID(deployment_id))
            if deployment is not None:
                return await _chat_with_deployment(
                    db, org_id, provider_override, deployment, messages,
                    system_prompt=system_prompt, temperature=temperature,
                    max_tokens=max_tokens, tools=tools,
                )
        return await legacy_client.chat(
            db, org_id, model_alias, messages, system_prompt=system_prompt,
            temperature=temperature, max_tokens=max_tokens, tools=tools,
            provider_override=provider_override, model_override=model_override,
        )
    candidates = await candidate_deployments(
        db, org_id, model_alias, "chat", dept_id=dept_id, team_id=team_id,
    )
    if not candidates:
        await _assert_legacy_fallback_allowed(
            db, org_id, model_alias, "chat", dept_id=dept_id, team_id=team_id,
        )
        return await legacy_client.chat(
            db, org_id, model_alias, messages, system_prompt=system_prompt,
            temperature=temperature, max_tokens=max_tokens, tools=tools,
            dept_id=dept_id, team_id=team_id,
        )
    last_error: Exception | None = None
    for index, (provider, deployment) in enumerate(candidates):
        try:
            return await _chat_with_deployment(
                db, org_id, provider, deployment, messages,
                system_prompt=system_prompt, temperature=temperature,
                max_tokens=max_tokens, tools=tools,
            )
        except Exception as exc:
            last_error = exc
            if index == len(candidates) - 1 or not _retryable(exc):
                raise
    assert last_error is not None
    raise last_error


async def chat(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    messages: list[dict],
    *,
    system_prompt: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    provider_override: LlmProvider | None = None,
    model_override: str | None = None,
) -> LlmResult:
    bounded_max = _bounded_max_tokens(max_tokens)
    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={
            "model": model_alias,
            "messages": messages,
            "system": system_prompt,
            "tools": tools,
        },
        max_output_tokens=bounded_max,
        dept_id=dept_id,
        team_id=team_id,
        operation="chat",
        provider_id=getattr(provider_override, "id", None),
    )

    async def invoke() -> LlmResult:
        return await _chat_unmetered(
            db,
            org_id,
            model_alias,
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=bounded_max,
            tools=tools,
            dept_id=dept_id,
            team_id=team_id,
            provider_override=provider_override,
            model_override=model_override,
        )

    return await _metered_result(db, reservation, invoke, lambda result: result.usage)


async def _stream_chat_unmetered(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    messages: list[dict],
    *,
    system_prompt: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    provider_override: LlmProvider | None = None,
    model_override: str | None = None,
) -> AsyncIterator[tuple[str, Any, Any]]:
    if provider_override is not None:
        deployment_id = str((provider_override.config or {}).get("_gateway_deployment_id") or "").strip()
        if deployment_id:
            deployment = await db.get(ModelDeployment, UUID(deployment_id))
            if deployment is not None and deployment.adapter == "openai_responses":
                result = await _responses_chat(
                    provider_override, deployment, messages, system_prompt=system_prompt,
                    temperature=temperature, max_tokens=max_tokens, tools=tools,
                )
                if result.content:
                    yield ("text", result.content, None)
                if result.tool_calls:
                    yield ("tool_calls", result.tool_calls, None)
                if result.reasoning_content:
                    yield ("reasoning_content", result.reasoning_content, None)
                yield ("usage", None, result.usage)
                return
        async for event in legacy_client.stream_chat(
            db, org_id, model_alias, messages, system_prompt=system_prompt,
            temperature=temperature, max_tokens=max_tokens, tools=tools,
            provider_override=provider_override, model_override=model_override,
        ):
            yield event
        return
    candidates = await candidate_deployments(
        db, org_id, model_alias, "chat", dept_id=dept_id, team_id=team_id,
    )
    if not candidates:
        await _assert_legacy_fallback_allowed(
            db, org_id, model_alias, "chat", dept_id=dept_id, team_id=team_id,
        )
        async for event in legacy_client.stream_chat(
            db, org_id, model_alias, messages, system_prompt=system_prompt,
            temperature=temperature, max_tokens=max_tokens, tools=tools,
            dept_id=dept_id, team_id=team_id,
        ):
            yield event
        return

    for index, (provider, deployment) in enumerate(candidates):
        emitted = False
        try:
            if deployment.adapter == "openai_responses":
                # The Responses adapter is normalized before emitting anything,
                # so a retryable upstream error can safely switch providers.
                result = await _responses_chat(
                    provider, deployment, messages, system_prompt=system_prompt,
                    temperature=temperature, max_tokens=max_tokens, tools=tools,
                )
                if result.content:
                    emitted = True
                    yield ("text", result.content, None)
                if result.tool_calls:
                    emitted = True
                    yield ("tool_calls", result.tool_calls, None)
                if result.reasoning_content:
                    emitted = True
                    yield ("reasoning_content", result.reasoning_content, None)
                emitted = True
                yield ("usage", None, result.usage)
                return
            async for event in legacy_client.stream_chat(
                db, org_id, deployment.model_id, messages, system_prompt=system_prompt,
                temperature=temperature, max_tokens=max_tokens, tools=tools,
                provider_override=effective_provider(provider, deployment),
                model_override=deployment.model_id,
            ):
                emitted = True
                yield event
            return
        except Exception as exc:
            # Once bytes/events reached the caller, switching providers would
            # splice two model answers together.  Failover is therefore allowed
            # only before the first emitted event and only for transient errors.
            if emitted or index == len(candidates) - 1 or not _retryable(exc):
                raise


async def stream_chat(
    db: AsyncSession,
    org_id: UUID,
    model_alias: str,
    messages: list[dict],
    *,
    system_prompt: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    provider_override: LlmProvider | None = None,
    model_override: str | None = None,
) -> AsyncIterator[tuple[str, Any, Any]]:
    bounded_max = _bounded_max_tokens(max_tokens)
    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={
            "model": model_alias,
            "messages": messages,
            "system": system_prompt,
            "tools": tools,
        },
        max_output_tokens=bounded_max,
        dept_id=dept_id,
        team_id=team_id,
        operation="stream-chat",
        provider_id=getattr(provider_override, "id", None),
    )
    usage: dict[str, int | None] = {"input_tokens": None, "output_tokens": None}
    completed = False
    try:
        async for event in _stream_chat_unmetered(
            db,
            org_id,
            model_alias,
            messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=bounded_max,
            tools=tools,
            dept_id=dept_id,
            team_id=team_id,
            provider_override=provider_override,
            model_override=model_override,
        ):
            if event[0] == "usage" and isinstance(event[2], dict):
                if event[2].get("input_tokens") is not None:
                    usage["input_tokens"] = int(event[2]["input_tokens"])
                if event[2].get("output_tokens") is not None:
                    usage["output_tokens"] = int(event[2]["output_tokens"])
            yield event
        completed = True
    finally:
        await settle_ai_quota(
            reservation,
            usage if completed else None,
            db=db,
            outcome="completed" if completed else "disconnected",
        )


async def _embed_unmetered(
    db: AsyncSession,
    org_id: UUID,
    model: str,
    texts: list[str],
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> tuple[list[list[float]], dict[str, Any]]:
    resolved = await resolve_deployment(
        db, org_id, model, "embedding", dept_id=dept_id, team_id=team_id,
    )
    if not resolved:
        await _assert_legacy_fallback_allowed(
            db, org_id, model, "embedding", dept_id=dept_id, team_id=team_id,
        )
        return await legacy_client.embed_with_usage(
            db, org_id, model, texts, dept_id=dept_id, team_id=team_id,
        )
    provider, deployment = resolved
    return await _embed_with_deployment(effective_provider(provider, deployment), deployment, texts)


async def embed(
    db: AsyncSession,
    org_id: UUID,
    model: str,
    texts: list[str],
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> list[list[float]]:
    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={"model": model, "input": texts},
        dept_id=dept_id,
        team_id=team_id,
        operation="embedding",
    )

    async def invoke() -> tuple[list[list[float]], dict[str, Any]]:
        return await _embed_unmetered(
            db,
            org_id,
            model,
            texts,
            dept_id=dept_id,
            team_id=team_id,
        )

    vectors, _usage = await _metered_result(db, reservation, invoke, lambda result: result[1])
    return vectors


async def _embed_with_deployment(
    provider: LlmProvider,
    deployment: ModelDeployment,
    texts: list[str],
) -> tuple[list[list[float]], dict[str, Any]]:
    """Call one explicit embedding deployment and enforce its declared dimensions."""
    if provider.provider_type == "anthropic":
        raise GatewayError("capability_mismatch")
    api_key = await get_decrypted_api_key(provider)
    path = _safe_endpoint_path(deployment.endpoint_path or "/embeddings", "Embeddings API")
    body: dict[str, Any] = {"model": deployment.model_id, "input": texts}
    if deployment.embedding_dimensions:
        body["dimensions"] = deployment.embedding_dimensions
    try:
        async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
            response = await client.post(
                f"{provider.base_url.rstrip('/')}{path}",
                headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise GatewayError("network_timeout") from exc
    except httpx.NetworkError as exc:
        raise GatewayError("network_failure") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise GatewayError("invalid_provider_response") from exc
    if response.status_code >= 400:
        raise GatewayError(_upstream_error_category(response.status_code, data))
    items = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
    if len(items) != len(texts):
        raise GatewayError("invalid_provider_response")
    vectors: list[list[float]] = []
    for item in items:
        vector = item.get("embedding")
        if not isinstance(vector, list) or not vector or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) for value in vector
        ):
            raise GatewayError("invalid_provider_response")
        if deployment.embedding_dimensions and len(vector) != deployment.embedding_dimensions:
            raise GatewayError("capability_mismatch")
        vectors.append(vector)
    raw_usage = data.get("usage") or {}
    prompt_tokens = raw_usage.get("prompt_tokens", raw_usage.get("input_tokens"))
    total_tokens = raw_usage.get("total_tokens")
    output_tokens = 0
    if total_tokens is not None and prompt_tokens is not None:
        output_tokens = max(0, int(total_tokens) - int(prompt_tokens))
    return vectors, {
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens if prompt_tokens is not None else None,
    }


async def _generate_image_unmetered(
    provider: LlmProvider,
    model: str,
    *,
    prompt: str,
    size: str,
    quality: str | None = None,
    endpoint_path: str = "/images/generations",
    max_bytes: int = 5 * 1024 * 1024,
) -> ImageGenerationResult:
    deployment = next(
        (
            item for item in (provider.model_deployments or [])
            if item.model_id == model
            and item.is_active
            and item.deleted_at is None
            and "image_generation" in (item.capabilities or [])
            and item.verification_status in _ROUTABLE_STATES
        ),
        None,
    )
    if deployment is None:
        return await legacy_client.generate_image(
            provider, model, prompt=prompt, size=size, quality=quality,
            endpoint_path=endpoint_path, max_bytes=max_bytes,
        )
    if deployment.adapter == "bailian_multimodal_generation":
        return await _bailian_generate_image(
            effective_provider(provider, deployment), deployment,
            prompt=prompt, size=size, max_bytes=max_bytes,
        )
    return await legacy_client.generate_image(
        effective_provider(provider, deployment), deployment.model_id,
        prompt=prompt, size=size, quality=quality,
        endpoint_path=deployment.endpoint_path or endpoint_path, max_bytes=max_bytes,
    )


async def generate_image(
    provider: LlmProvider,
    model: str,
    *,
    prompt: str,
    size: str,
    quality: str | None = None,
    endpoint_path: str = "/images/generations",
    max_bytes: int = 5 * 1024 * 1024,
    db: AsyncSession | None = None,
    org_id: UUID | None = None,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> ImageGenerationResult:
    if db is None or org_id is None:
        if not settings.is_development:
            raise GatewayError("quota_context_required")
        return await _generate_image_unmetered(
            provider,
            model,
            prompt=prompt,
            size=size,
            quality=quality,
            endpoint_path=endpoint_path,
            max_bytes=max_bytes,
        )
    reservation = await _reserve_gateway_quota(
        db,
        org_id,
        payload={"model": model, "prompt": prompt, "size": size, "quality": quality},
        dept_id=dept_id,
        team_id=team_id,
        supports_token_metering=False,
        operation="image-generation",
        provider_id=getattr(provider, "id", None),
    )

    async def invoke() -> ImageGenerationResult:
        return await _generate_image_unmetered(
            provider,
            model,
            prompt=prompt,
            size=size,
            quality=quality,
            endpoint_path=endpoint_path,
            max_bytes=max_bytes,
        )

    return await _metered_result(db, reservation, invoke, lambda _result: None)


async def _bailian_generate_image(
    provider: LlmProvider,
    deployment: ModelDeployment,
    *,
    prompt: str,
    size: str,
    max_bytes: int,
) -> ImageGenerationResult:
    """Call Bailian's synchronous multimodal-generation image endpoint."""
    api_key = await get_decrypted_api_key(provider)
    base = provider.base_url.rstrip("/")
    for suffix in ("/compatible-mode/v1", "/apps/anthropic"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    path = _safe_endpoint_path(
        deployment.endpoint_path or "/api/v1/services/aigc/multimodal-generation/generation",
        "Bailian image API",
    )
    requested_size = str((deployment.config or {}).get("default_size") or size)
    body = {
        "model": deployment.model_id,
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": {
            "size": _normalize_bailian_image_size(requested_size),
            "n": 1,
            "watermark": bool((deployment.config or {}).get("watermark", False)),
        },
    }
    async with httpx.AsyncClient(timeout=provider.timeout_seconds, follow_redirects=False) as client:
        response = await client.post(
            f"{base}{path}",
            headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json=body,
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise GatewayError("invalid_provider_response") from exc
        if response.status_code >= 400:
            raise GatewayError(_upstream_error_category(response.status_code, data))
        image_url = ""
        for choice in (data.get("output") or {}).get("choices") or []:
            for item in ((choice.get("message") or {}).get("content") or []):
                if item.get("image"):
                    image_url = str(item["image"])
                    break
            if image_url:
                break
        if not image_url:
            raise GatewayError("invalid_provider_response")
        legacy_client._assert_public_image_url(image_url)
        async with client.stream("GET", image_url) as image_response:
            if image_response.status_code >= 300:
                raise GatewayError(_upstream_error_category(image_response.status_code))
            chunks: list[bytes] = []
            total = 0
            async for chunk in image_response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError("generated image exceeds the 5MB limit")
                chunks.append(chunk)
            raw = b"".join(chunks)
    if not raw:
        raise GatewayError("invalid_provider_response")
    return ImageGenerationResult(
        raw=raw, provider_id=str(provider.id), model_served=deployment.model_id,
    )


async def _test_deployment_unmetered(
    db: AsyncSession,
    provider: LlmProvider,
    deployment: ModelDeployment,
    capability: str,
) -> dict[str, Any]:
    """Perform an explicit billable-capability test. The caller owns transaction state."""
    effective = effective_provider(provider, deployment)
    if capability in {"chat", "vision"}:
        content: Any = "Do not explain. Reply exactly with OK."
        if capability == "vision":
            content = [
                {"type": "text", "text": "Do not explain. Reply exactly with OK."},
                {"type": "image_url", "image_url": {"url": _TEST_IMAGE_DATA_URL}},
            ]
        # Vision-capable reasoning models can spend the small verification
        # budget entirely on hidden reasoning and return no final text.  Keep
        # ordinary chat checks cheap while leaving vision enough room to emit
        # the requested answer.
        verification_max_tokens = 512 if capability == "vision" else 128
        result = await _chat_with_deployment(
            db, provider.organization_id, provider, deployment,
            [{"role": "user", "content": content}], system_prompt="",
            temperature=0, max_tokens=verification_max_tokens, tools=None,
        )
        output = (result.content or "").strip()
        if not output:
            raise GatewayError("invalid_provider_response")
        return {
            "output": output[:200],
            "provider_id": result.provider_id,
            "usage": result.usage,
        }
    if capability == "embedding":
        vectors, usage = await _embed_with_deployment(
            effective,
            deployment,
            ["gateway health check"],
        )
        return {
            "dimensions": len(vectors[0]) if vectors else 0,
            "usage": usage,
        }
    if capability == "image_generation":
        if deployment.adapter == "bailian_multimodal_generation":
            image = await _bailian_generate_image(
                effective, deployment, prompt="A simple blue circle on white background",
                size=str((deployment.config or {}).get("default_size") or "1024x1024"),
                max_bytes=5 * 1024 * 1024,
            )
        else:
            image = await legacy_client.generate_image(
                effective, deployment.model_id, prompt="A simple blue circle on white background",
                size=str((deployment.config or {}).get("default_size") or "1024x1024"),
                endpoint_path=deployment.endpoint_path or "/images/generations",
            )
        return {"bytes": len(image.raw)}
    if capability in {
        "audio_understanding", "speech_to_text", "text_to_speech", "voice_design", "voice_clone",
    }:
        audio_bytes = _test_wav_bytes()
        if test_file_id := str((deployment.config or {}).get("test_workspace_file_id") or "").strip():
            from app.models.workspace import Workspace, WorkspaceFile
            from app.services.storage_gateway_service import download_bytes

            try:
                parsed_test_file_id = UUID(test_file_id)
            except ValueError as exc:
                raise GatewayError("invalid_test_audio_configuration") from exc
            test_file = (await db.execute(
                select(WorkspaceFile)
                .join(Workspace, Workspace.id == WorkspaceFile.workspace_id)
                .where(
                    WorkspaceFile.id == parsed_test_file_id,
                    WorkspaceFile.deleted_at.is_(None),
                    Workspace.organization_id == provider.organization_id,
                    Workspace.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if test_file is None or not test_file.content_ref:
                raise GatewayError("invalid_test_audio_configuration")
            audio_bytes = await download_bytes(test_file.content_ref)
        encoded = base64.b64encode(audio_bytes).decode("ascii")
        if capability in {"audio_understanding", "speech_to_text"}:
            body: dict[str, Any] = {
                "model": deployment.model_id,
                "messages": [{
                    "role": "user",
                    "content": [{
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:audio/wav;base64,{encoded}",
                        },
                    }],
                }],
                "stream": False,
            }
            if capability == "audio_understanding":
                body["messages"][0]["content"].append({"type": "text", "text": "Describe this audio briefly."})
            else:
                body["asr_options"] = {"language": "auto"}
            data = await _post_chat_json(effective, deployment, body)
            message, usage = _message_content(data)
            output = message.get("content") or message.get("reasoning_content") or ""
            return {"output": str(output)[:200], "usage": usage}
        messages: list[dict[str, Any]] = []
        if capability == "voice_design":
            messages.append({"role": "user", "content": "温暖、清晰、专业的普通话女声"})
        messages.append({"role": "assistant", "content": "灼见语音能力测试。"})
        audio: dict[str, Any] = {"format": "wav"}
        if capability == "voice_design":
            audio["optimize_text_preview"] = False
        if capability == "voice_clone":
            if not (deployment.config or {}).get("test_workspace_file_id"):
                raise GatewayError("test_voice_sample_required")
            audio["voice"] = f"data:audio/wav;base64,{encoded}"
        body = {"model": deployment.model_id, "messages": messages, "audio": audio, "stream": False}
        data = await _post_chat_json(effective, deployment, body)
        message, usage = _message_content(data)
        audio_payload = message.get("audio") or {}
        raw = base64.b64decode(str(audio_payload.get("data") or ""))
        if not raw:
            raise GatewayError("invalid_provider_response")
        return {"bytes": len(raw), "usage": usage}
    raise ValueError(f"unsupported capability: {capability}")


async def test_deployment(
    db: AsyncSession,
    provider: LlmProvider,
    deployment: ModelDeployment,
    capability: str,
) -> dict[str, Any]:
    """Billable verification calls use the tenant's normal quota boundary."""

    reservation = await _reserve_gateway_quota(
        db,
        UUID(str(provider.organization_id)),
        payload={
            "capability": capability,
            "model": deployment.model_id,
            "purpose": "provider_verification",
        },
        max_output_tokens=(
            512
            if capability in {"chat", "vision", "audio_understanding"}
            else settings.ai_quota_default_max_output_tokens
        ),
        dept_id=getattr(provider, "department_id", None),
        team_id=getattr(provider, "team_id", None),
        supports_token_metering=capability not in {
            "image_generation",
            "audio_understanding",
            "speech_to_text",
            "text_to_speech",
            "voice_design",
            "voice_clone",
        },
        operation="provider-verification",
        provider_id=getattr(provider, "id", None),
    )

    async def invoke() -> dict[str, Any]:
        return await _test_deployment_unmetered(db, provider, deployment, capability)

    return await _metered_result(db, reservation, invoke, lambda result: result.get("usage"))


def _test_wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\x00\x00" * 16000)
    return output.getvalue()


async def test_provider_connection(provider: LlmProvider) -> dict[str, str]:
    """Validate credentials without returning upstream payloads or credential material."""
    api_key = await get_decrypted_api_key(provider)
    effective_type = "anthropic" if provider.provider_type == "anthropic" else "openai"
    headers = (
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        if effective_type == "anthropic"
        else {"authorization": f"Bearer {api_key}"}
    )
    base = provider.base_url.rstrip("/")
    path = "/v1/models" if effective_type == "anthropic" and not base.endswith("/v1") else "/models"
    try:
        async with httpx.AsyncClient(timeout=min(provider.timeout_seconds, 30)) as client:
            response = await client.get(f"{base}{path}", headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise RuntimeError("network_failure") from exc
    if response.status_code in {401, 403}:
        raise RuntimeError("invalid_credentials_or_permission")
    if response.status_code == 404:
        raise RuntimeError("endpoint_not_supported")
    if response.status_code == 429:
        raise RuntimeError("quota_or_rate_limit")
    if response.status_code >= 500:
        raise RuntimeError("provider_service_unavailable")
    if response.status_code >= 400:
        raise RuntimeError("provider_rejected_request")
    return {"status": "verified", "vendor": provider.vendor, "detail": "凭证有效，供应商连接成功"}
