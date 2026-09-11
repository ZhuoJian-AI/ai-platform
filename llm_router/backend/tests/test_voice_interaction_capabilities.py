"""Availability is explanatory, never a substitute for runtime authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import multimodal_audio_service as audio


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,permissions,deployed,voice,expected",
    [
        (False, ["*"], True, True, ("disabled", "disabled")),
        (True, [], True, True, ("permission_denied", "permission_denied")),
        (True, ["multimodal.audio.transcribe"], True, True, ("available", "permission_denied")),
        (True, ["*"], False, True, ("no_available_deployment", "no_available_deployment")),
        (True, ["*"], True, False, ("available", "no_available_voice")),
        (True, ["*"], True, True, ("available", "available")),
    ],
)
async def test_capability_availability(monkeypatch, enabled, permissions, deployed, voice, expected):
    org_id = uuid4()
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=org_id, slug="test")))
    cu = SimpleNamespace(organization_id=org_id, permission_codes=permissions, department_id=None)
    monkeypatch.setattr(audio, "settings", SimpleNamespace(multimodal_audio_enabled_for=lambda *a, **kw: enabled))
    route = AsyncMock(return_value=(object(), object()) if deployed else None)
    monkeypatch.setattr(audio.model_gateway, "resolve_deployment", route)
    monkeypatch.setattr(audio, "list_visible_voices", AsyncMock(
        return_value=[SimpleNamespace(voice_type="builtin")] if voice else [],
    ))
    result = await audio.interaction_capabilities(db, cu)
    assert tuple(value["code"] for value in result.values()) == expected
    assert all(value["available"] == (value["code"] == "available") for value in result.values())
    assert all(value["messageZh"] for value in result.values())
    if not enabled or not permissions:
        route.assert_not_awaited()
