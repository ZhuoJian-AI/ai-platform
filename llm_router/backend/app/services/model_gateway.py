"""Capability-aware model gateway used by Agent Runtime and RAG.

The gateway owns provider/deployment selection and wire-protocol adaptation.  It
does not plan agent work, execute Skills, or persist workspace files.  Existing
providers without explicit deployments remain available through the legacy
client so the rollout is backwards compatible.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import llm_client as legacy_client
from app.config import settings
from app.models.llm_provider import LlmProvider, ModelDeployment
from app.models.organization import Organization
from app.services.llm_provider_service import effective_provider, get_decrypted_api_key

LlmResult = legacy_client.LlmResult
ImageGenerationResult = legacy_client.ImageGenerationResult

_SCOPE_RANK = {"team": 3, "department": 2, "organization": 1}
_ROUTABLE_STATES = {"verified", "legacy"}
_RETRYABLE_MARKERS = (" 429", " 500", " 502", " 503", " 504", "timeout", "timed out", "connect")


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
        organization and settings.model_gateway_enabled_for(organization.slug)
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
        raise RuntimeError("模型部署尚未完成全部能力验证，或该组织尚未启用新模型网关")


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
    lowered = str(exc).lower()
    return any(marker in lowered for marker in _RETRYABLE_MARKERS)


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
    path = deployment.endpoint_path or "/responses"
    if not path.startswith("/") or "://" in path or ".." in path:
        raise RuntimeError("invalid Responses API endpoint path")
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
        raise RuntimeError(f"upstream Responses API error {response.status_code}: invalid JSON") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"upstream Responses API error {response.status_code}: {data}")
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


async def embed(
    db: AsyncSession,
    org_id: UUID,
    model: str,
    texts: list[str],
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
) -> list[list[float]]:
    resolved = await resolve_deployment(
        db, org_id, model, "embedding", dept_id=dept_id, team_id=team_id,
    )
    if not resolved:
        await _assert_legacy_fallback_allowed(
            db, org_id, model, "embedding", dept_id=dept_id, team_id=team_id,
        )
        return await legacy_client.embed(
            db, org_id, model, texts, dept_id=dept_id, team_id=team_id,
        )
    provider, deployment = resolved
    return await legacy_client.embed(
        db, org_id, deployment.model_id, texts,
        provider_override=effective_provider(provider, deployment),
        model_override=deployment.model_id,
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
    path = deployment.endpoint_path or "/api/v1/services/aigc/multimodal-generation/generation"
    if not path.startswith("/") or "://" in path or ".." in path:
        raise RuntimeError("invalid Bailian image endpoint path")
    body = {
        "model": deployment.model_id,
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": {
            "size": str((deployment.config or {}).get("default_size") or size),
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
            raise RuntimeError(f"upstream Bailian image error {response.status_code}: invalid JSON") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"upstream Bailian image error {response.status_code}")
        image_url = ""
        for choice in (data.get("output") or {}).get("choices") or []:
            for item in ((choice.get("message") or {}).get("content") or []):
                if item.get("image"):
                    image_url = str(item["image"])
                    break
            if image_url:
                break
        if not image_url:
            raise RuntimeError("Bailian image generation returned no image URL")
        legacy_client._assert_public_image_url(image_url)
        async with client.stream("GET", image_url) as image_response:
            if image_response.status_code >= 300:
                raise RuntimeError(f"generated image download failed ({image_response.status_code})")
            chunks: list[bytes] = []
            total = 0
            async for chunk in image_response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError("generated image exceeds the 5MB limit")
                chunks.append(chunk)
            raw = b"".join(chunks)
    if not raw:
        raise RuntimeError("generated image is empty")
    return ImageGenerationResult(
        raw=raw, provider_id=str(provider.id), model_served=deployment.model_id,
    )


async def test_deployment(
    db: AsyncSession,
    provider: LlmProvider,
    deployment: ModelDeployment,
    capability: str,
) -> dict[str, Any]:
    """Perform an explicit billable-capability test. The caller owns transaction state."""
    effective = effective_provider(provider, deployment)
    if capability in {"chat", "vision"}:
        content: Any = "Reply with OK only."
        if capability == "vision":
            test_image = (
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            content = [
                {"type": "text", "text": "Reply with OK only."},
                {"type": "image_url", "image_url": {"url": test_image}},
            ]
        result = await _chat_with_deployment(
            db, provider.organization_id, provider, deployment,
            [{"role": "user", "content": content}], system_prompt="",
            temperature=0, max_tokens=8, tools=None,
        )
        return {"output": result.content[:200], "provider_id": result.provider_id}
    if capability == "embedding":
        vectors = await legacy_client.embed(
            db, provider.organization_id, deployment.model_id, ["gateway health check"],
            provider_override=effective, model_override=deployment.model_id,
        )
        return {"dimensions": len(vectors[0]) if vectors else 0}
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
    raise ValueError(f"unsupported capability: {capability}")


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
