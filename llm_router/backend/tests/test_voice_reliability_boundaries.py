"""Regression tests for public audio output and workspace identity boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api import multimodal
from app.services import multimodal_audio_service as audio
from app.services import workspace_permission_service as permissions
from app.services.model_gateway import GatewayError


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["workspace_org", "user_org", "user_id"])
@pytest.mark.parametrize("null_value", [False, True])
async def test_missing_identity_never_grants_workspace_access(missing, null_value):
    workspace = SimpleNamespace(organization_id="tenant", scope_type="user", scope_id="user")
    user = SimpleNamespace(organization_id="tenant", id="user", permission_codes=["*"])
    obj, field = {
        "workspace_org": (workspace, "organization_id"),
        "user_org": (user, "organization_id"),
        "user_id": (user, "id"),
    }[missing]
    if null_value:
        setattr(obj, field, None)
    else:
        delattr(obj, field)
    assert not permissions.is_workspace_readable(workspace, user)
    assert not any((await permissions.capabilities(None, workspace, user)).values())
    assert permissions.capability_sources(workspace, user) == {}


@pytest.mark.asyncio
async def test_complete_projection_retains_personal_ownership():
    workspace = SimpleNamespace(organization_id="tenant", scope_type="user", scope_id="user")
    user = SimpleNamespace(organization_id="tenant", id="user", permission_codes=[])
    result = await permissions.capabilities(None, workspace, user)
    assert all(result[key] for key in ("read", "create", "update", "delete"))


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [None, "", "  ", "这是有效答案"])
async def test_audio_service_never_returns_reasoning(monkeypatch, answer):
    monkeypatch.setattr(audio, "require_multimodal_enabled", AsyncMock())
    monkeypatch.setattr(audio, "_visible_audio_file", AsyncMock(
        return_value=SimpleNamespace(content_ref="ref", size=1),
    ))
    monkeypatch.setattr(audio.storage_gateway_service, "get_browser_signed_download", AsyncMock(return_value={"url": "https://example.test/audio"}))
    monkeypatch.setattr(audio.model_gateway, "understand_audio", AsyncMock(return_value=SimpleNamespace(
        content=answer, reasoning_content="PRIVATE_REASONING", model_served="audio", usage={},
    )))
    user = SimpleNamespace(
        organization_id=uuid4(), department_id=None, permission_codes=["multimodal.audio.understand"],
    )
    if not answer or not answer.strip():
        with pytest.raises(GatewayError, match="empty_response"):
            await audio.understand_file(None, user, uuid4(), "问题", "default")
    else:
        result = await audio.understand_file(None, user, uuid4(), "问题", "default")
        assert result["content"] == answer
        assert "reasoning_content" not in result
        assert "PRIVATE_REASONING" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [None, "  ", "这是有效答案"])
async def test_audio_stream_ignores_reasoning_and_requires_answer(monkeypatch, answer):
    async def stream():
        yield "reasoning_content", "PRIVATE_REASONING", None
        if answer is not None:
            yield "text", answer, None
        yield "reasoning_content", "MORE_PRIVATE_REASONING", None
        yield "usage", None, {"tokens": 1}

    monkeypatch.setattr(audio, "stream_understand_file", AsyncMock(return_value=stream()))
    data = SimpleNamespace(workspace_file_id=uuid4(), question="问题", model="default")
    response = await multimodal.understand_audio(data, None, None)
    output = "".join([chunk async for chunk in response.body_iterator])
    assert "PRIVATE_REASONING" not in output
    if answer and answer.strip():
        assert "event: done" in output
        assert answer in output
    else:
        assert "empty_response" in output
        assert '"retryable": true' in output
        assert "event: done" not in output
