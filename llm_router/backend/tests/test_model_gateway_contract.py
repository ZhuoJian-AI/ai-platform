"""Pure model-gateway contracts that do not require PostgreSQL."""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
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

    assert captured["max_tokens"] == 512


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


@pytest.mark.asyncio
async def test_failed_capability_test_commits_revocation_through_request_transaction(monkeypatch):
    """Exercise the real get_db transaction boundary, including its rollback path."""
    from app import database
    from app.api import llm_providers

    provider = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    deployment = SimpleNamespace(
        provider_id=provider.id,
        capabilities=["chat", "vision"],
        config={"verified_capabilities": ["chat", "vision"], "other_setting": True},
        verification_status="verified",
        last_error=None,
    )
    persisted = {}

    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def flush(self):
            pass

        async def commit(self):
            persisted.update(deepcopy(vars(deployment)))

        async def rollback(self):
            persisted["rolled_back"] = True

    async def get_provider(*_args):
        return provider

    async def get_deployment(*_args):
        return deployment

    async def reject(*_args):
        raise model_gateway.GatewayError("invalid_provider_response")

    monkeypatch.setattr(database, "async_session_factory", Transaction)
    monkeypatch.setattr(llm_providers, "get_provider", get_provider)
    monkeypatch.setattr(llm_providers, "get_model_deployment", get_deployment)
    monkeypatch.setattr(llm_providers, "assert_org_write_access", lambda *_args: None)
    monkeypatch.setattr(llm_providers, "test_deployment", reject)

    async with asynccontextmanager(database.get_db)() as db:
        response = await llm_providers.test_model_deployment_endpoint(
            provider.id, uuid4(), "chat", auth=object(), db=db,
        )

    assert response.status_code == 400
    assert json.loads(response.body)["detail"] == "供应商返回了无法识别的响应"
    assert persisted["verification_status"] == "failed"
    assert persisted["config"] == {"verified_capabilities": ["vision"], "other_setting": True}
    assert persisted["last_error"] == "invalid_provider_response"
    assert "rolled_back" not in persisted
