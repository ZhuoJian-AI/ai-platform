"""Pure model-gateway contracts that do not require PostgreSQL."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.llm_provider import LlmProviderCreate
from app.services import model_gateway
from app.services.llm_provider_service import provider_base_url


@pytest.fixture(autouse=True)
def db_engine():
    yield


@pytest.fixture(autouse=True)
def _isolate_gateway_contracts_from_quota(monkeypatch):
    async def allow(*_args, **_kwargs):
        return model_gateway.QuotaReservation("gateway-contract-test", 0, enforced=False)

    monkeypatch.setattr(model_gateway, "_reserve_gateway_quota", allow)


def test_compatible_endpoints_are_keyed_by_wire_protocol() -> None:
    assert provider_base_url(
        "openai", region=None, workspace_id=None, provider_type="openai",
        explicit="https://compatible.example.com/v1/",
    ) == "https://compatible.example.com/v1"
    assert provider_base_url(
        "anthropic", region=None, workspace_id=None, provider_type="anthropic",
        explicit="https://anthropic-compatible.example.com/anthropic/",
    ) == "https://anthropic-compatible.example.com/anthropic"

    provider = LlmProviderCreate(
        name="compatible-models",
        vendor="openai",
        provider_type="openai",
        base_url="https://compatible.example.com/v1",
        api_key="provider-specific-prefix-test",
    )
    assert provider.vendor == "openai"

    with pytest.raises(ValidationError, match="unsupported vendor"):
        LlmProviderCreate(
            name="obsolete-pseudo-vendor", vendor="xiaomi_mimo", api_key="test-key",
        )


@pytest.mark.asyncio
async def test_chat_verification_requires_a_final_answer_and_allows_reasoning_budget(monkeypatch) -> None:
    provider = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    deployment = SimpleNamespace(model_id="reasoning-model")
    captured: dict = {}

    async def reasoning_only(*_args, **kwargs):
        captured.update(kwargs)
        return model_gateway.LlmResult(
            content="", tool_calls=[], usage={"input_tokens": 3, "output_tokens": 8},
            provider_id=str(provider.id), model_served=deployment.model_id,
            reasoning_content="internal reasoning without a final answer",
        )

    monkeypatch.setattr(model_gateway, "effective_provider", lambda value, _deployment: value)
    monkeypatch.setattr(model_gateway, "_chat_with_deployment", reasoning_only)

    with pytest.raises(model_gateway.GatewayError, match="invalid_provider_response"):
        await model_gateway.test_deployment(object(), provider, deployment, "chat")

    assert captured["max_tokens"] == 128


@pytest.mark.asyncio
async def test_unverified_deployment_blocks_legacy_fallback_with_stable_category(monkeypatch) -> None:
    deployment = SimpleNamespace(verification_status="unverified")

    async def candidates(*_args, **_kwargs):
        return [(SimpleNamespace(), deployment)]

    monkeypatch.setattr(model_gateway, "candidate_deployments", candidates)

    with pytest.raises(model_gateway.GatewayError) as raised:
        await model_gateway._assert_legacy_fallback_allowed(
            object(), uuid4(), "reasoning-model", "chat",
        )

    assert raised.value.category == "deployment_not_verified"
