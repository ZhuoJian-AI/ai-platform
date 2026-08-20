"""Model gateway engineering acceptance tests (no real provider credentials)."""

import base64
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.llm_provider import LlmProvider, ModelDeployment
from app.schemas.llm_provider import ModelDeploymentCreate
from app.services import model_gateway
from app.services.llm_provider_service import provider_base_url
from app.utils.crypto import encrypt_provider_api_key


def test_bailian_and_ark_endpoint_presets():
    assert provider_base_url(
        "aliyun_bailian", region="cn-beijing", workspace_id="llm-demo",
        provider_type="openai", explicit=None,
    ) == "https://llm-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert provider_base_url(
        "aliyun_bailian", region="ap-southeast-1", workspace_id=None,
        provider_type="anthropic", explicit=None,
    ) == "https://dashscope-intl.aliyuncs.com/apps/anthropic"
    assert provider_base_url(
        "volcengine_ark", region="cn-beijing", workspace_id=None,
        provider_type="openai", explicit=None,
    ) == "https://ark.cn-beijing.volces.com/api/v3"
    with pytest.raises(ValueError, match="credentials"):  # URL credentials are never accepted.
        provider_base_url(
            "custom", region=None, workspace_id=None, provider_type="openai",
            explicit="https://user:pass@example.com/v1",
        )


def test_deployment_schema_rejects_capability_adapter_mismatch():
    with pytest.raises(ValueError, match="only declare embedding"):
        ModelDeploymentCreate(
            model_id="bge-m3", adapter="openai_embeddings", capabilities=["chat", "embedding"],
        )
    with pytest.raises(ValueError, match="image_generation"):
        ModelDeploymentCreate(
            model_id="seedream", adapter="volcengine_images", capabilities=["chat"],
        )


@pytest.mark.asyncio
async def test_create_bailian_provider_and_mask_secret(client: AsyncClient, monkeypatch):
    organization = (await client.post(
        "/api/v1/organizations", json={"name": "网关测试企业", "slug": "gateway-test"},
    )).json()
    response = await client.post(
        f"/api/v1/organizations/{organization['id']}/providers",
        json={
            "name": "百炼生产空间",
            "vendor": "aliyun_bailian",
            "provider_type": "openai",
            "region": "cn-beijing",
            "workspace_id": "llm-demo",
            "access_mode": "payg",
            "api_key": "sk-test-never-return",
            "scope_type": "organization",
            "model_deployments": [
                {
                    "model_id": "qwen-plus",
                    "adapter": "openai_chat_completions",
                    "capabilities": ["chat", "vision"],
                },
                {
                    "model_id": "text-embedding-v4",
                    "adapter": "openai_embeddings",
                    "capabilities": ["embedding"],
                    "embedding_dimensions": 1024,
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["vendor"] == "aliyun_bailian"
    assert data["base_url"] == "https://llm-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert data["api_key_masked"]
    assert "api_key_encrypted" not in data
    assert "sk-test-never-return" not in response.text
    assert {item["verification_status"] for item in data["model_deployments"]} == {"unverified"}

    async def successful_test(*_args, **_kwargs):
        return {"ok": True}

    monkeypatch.setattr("app.api.llm_providers.test_deployment", successful_test)
    vision_model = next(item for item in data["model_deployments"] if "vision" in item["capabilities"])
    chat_check = await client.post(
        f"/api/v1/providers/{data['id']}/models/{vision_model['id']}/test/chat"
    )
    assert chat_check.status_code == 200, chat_check.text
    assert chat_check.json()["status"] == "partially_verified"
    vision_check = await client.post(
        f"/api/v1/providers/{data['id']}/models/{vision_model['id']}/test/vision"
    )
    assert vision_check.status_code == 200, vision_check.text
    assert vision_check.json()["status"] == "verified"


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    calls: list[tuple[str, dict]] = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, json, **_kwargs):
        self.calls.append((url, json))
        if url.endswith("/responses"):
            return _FakeResponse({
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
                "usage": {"input_tokens": 3, "output_tokens": 1},
            })
        if url.endswith("/embeddings"):
            return _FakeResponse({"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
        if url.endswith("/images/generations"):
            return _FakeResponse({"data": [{"b64_json": base64.b64encode(b"fake-png").decode()}]})
        raise AssertionError(f"unexpected URL: {url}")


def _provider() -> LlmProvider:
    return LlmProvider(
        id=uuid4(), organization_id=uuid4(), name="Mock Gateway", vendor="volcengine_ark",
        provider_type="openai", scope_type="organization", base_url="https://mock.local/api/v3",
        api_key_encrypted=encrypt_provider_api_key("mock-secret"), supported_models=[], config={},
        timeout_seconds=30, priority=0, weight=1, max_retries=2, is_active=True,
    )


def _deployment(provider: LlmProvider, *, model_id: str, adapter: str, capabilities: list[str], path=None):
    return ModelDeployment(
        id=uuid4(), provider_id=provider.id, model_id=model_id, adapter=adapter,
        capabilities=capabilities, endpoint_path=path, routing_priority=0,
        is_active=True, verification_status="unverified", config={},
    )


@pytest.mark.asyncio
async def test_mock_gateway_chat_vision_embedding_image_and_stream(monkeypatch, db_session):
    _FakeClient.calls = []
    monkeypatch.setattr(model_gateway.httpx, "AsyncClient", _FakeClient)
    provider = _provider()
    chat = _deployment(
        provider, model_id="ep-chat", adapter="openai_responses", capabilities=["chat", "vision"],
        path="/responses",
    )
    embedding = _deployment(
        provider, model_id="ep-embedding", adapter="openai_embeddings", capabilities=["embedding"],
    )
    image = _deployment(
        provider, model_id="ep-image", adapter="volcengine_images", capabilities=["image_generation"],
        path="/images/generations",
    )

    chat_result = await model_gateway.test_deployment(db_session, provider, chat, "chat")
    vision_result = await model_gateway.test_deployment(db_session, provider, chat, "vision")
    embedding_result = await model_gateway.test_deployment(db_session, provider, embedding, "embedding")
    image_result = await model_gateway.test_deployment(db_session, provider, image, "image_generation")

    assert chat_result["output"] == "OK"
    assert vision_result["output"] == "OK"
    assert embedding_result["dimensions"] == 3
    assert image_result["bytes"] == len(b"fake-png")
    vision_bodies = [body for url, body in _FakeClient.calls if url.endswith("/responses")]
    assert any("input_image" in str(body) for body in vision_bodies)


@pytest.mark.asyncio
async def test_stream_fails_over_only_before_first_event(monkeypatch, db_session):
    first_provider = _provider()
    second_provider = _provider()
    first = _deployment(
        first_provider, model_id="shared-chat", adapter="openai_responses", capabilities=["chat"],
    )
    second = _deployment(
        second_provider, model_id="shared-chat", adapter="openai_responses", capabilities=["chat"],
    )

    async def fake_candidates(*_args, **_kwargs):
        return [(first_provider, first), (second_provider, second)]

    calls = []

    async def fake_responses(provider, *_args, **_kwargs):
        calls.append(provider.id)
        if provider.id == first_provider.id:
            raise RuntimeError("upstream 503")
        return model_gateway.LlmResult(
            content="fallback-ok", tool_calls=[], usage={},
            provider_id=str(provider.id), model_served="shared-chat",
        )

    monkeypatch.setattr(model_gateway, "candidate_deployments", fake_candidates)
    monkeypatch.setattr(model_gateway, "_responses_chat", fake_responses)

    events = [
        event async for event in model_gateway.stream_chat(
            db_session, first_provider.organization_id, "shared-chat",
            [{"role": "user", "content": "hello"}],
        )
    ]
    assert calls == [first_provider.id, second_provider.id]
    assert events[0] == ("text", "fallback-ok", None)
