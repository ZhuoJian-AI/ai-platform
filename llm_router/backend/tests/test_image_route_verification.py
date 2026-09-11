from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import multimodal_service


@pytest.fixture(autouse=True)
def db_engine():
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("status,active", [("unverified", True), ("failed", True), ("verified", False)])
async def test_legacy_image_alias_cannot_bypass_deployment_gate(monkeypatch, status, active):
    deployment = SimpleNamespace(
        model_id="image-model", is_active=active, deleted_at=None,
        verification_status=status, capabilities=["image_generation"], routing_priority=1,
    )
    provider = SimpleNamespace(model_deployments=[deployment], provider_type="openai", supported_models=["image-model"])

    async def flags(*args):
        return True, True

    async def providers(*args, **kwargs):
        return [provider]

    monkeypatch.setattr(multimodal_service, "organization_feature_flags", flags)
    monkeypatch.setattr(multimodal_service, "visible_providers", providers)
    monkeypatch.setattr(multimodal_service, "provider_image_generation_model", lambda _: "image-model")
    assert await multimodal_service.resolve_image_generation(None, uuid4()) is None
