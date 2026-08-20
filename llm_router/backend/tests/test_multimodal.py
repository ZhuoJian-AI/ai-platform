from __future__ import annotations

import base64
import io
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app.agents import llm_client
from app.services.multimodal_service import (
    ensure_image_batch_limits,
    normalize_generated_png,
    prepare_image_bytes,
    provider_model_supports_vision,
    validate_provider_config,
)


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db():
    """These pure adapter tests intentionally do not require PostgreSQL."""
    yield


@pytest.fixture(autouse=True)
def db_engine(_ensure_test_db):
    yield None


def _image_bytes(fmt: str, color: str = "red") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (12, 8), color).save(output, format=fmt)
    return output.getvalue()


def test_provider_config_normalizes_multimodal_fields() -> None:
    config = validate_provider_config({
        "model_capabilities": {"vision-chat": {"vision": True}},
        "vision_fallback_model": "vision-chat",
        "image_generation": {
            "enabled": True,
            "model": "image-model",
            "endpoint_path": "/images/generations",
            "default_size": "1024x1024",
        },
    }, ["vision-chat", "image-model"])
    assert config["model_capabilities"]["vision-chat"]["vision"] is True
    assert config["vision_fallback_model"] == "vision-chat"
    assert config["image_generation"]["model"] == "image-model"


def test_provider_config_rejects_unknown_or_unsafe_models() -> None:
    with pytest.raises(ValueError, match="supported_models"):
        validate_provider_config({"vision_fallback_model": "missing"}, ["text-model"])
    with pytest.raises(ValueError, match="endpoint_path"):
        validate_provider_config({
            "image_generation": {"enabled": True, "model": "image", "endpoint_path": "https://evil.test/x"},
        }, ["image"])


def test_prepare_image_validates_magic_and_converts_bmp() -> None:
    png = prepare_image_bytes(
        file_id="one", name="sample.png", declared_mime="image/png", raw=_image_bytes("PNG"),
    )
    assert png.mime_type == "image/png"
    assert (png.width, png.height) == (12, 8)
    bmp = prepare_image_bytes(
        file_id="two", name="sample.bmp", declared_mime="image/bmp", raw=_image_bytes("BMP"),
    )
    assert bmp.mime_type == "image/png"
    assert bmp.raw.startswith(b"\x89PNG")
    ensure_image_batch_limits([png, bmp])


def test_prepare_image_rejects_extension_mime_and_corruption() -> None:
    with pytest.raises(ValueError, match="MIME"):
        prepare_image_bytes(
            file_id="one", name="sample.png", declared_mime="image/jpeg", raw=_image_bytes("PNG"),
        )
    with pytest.raises(ValueError, match="损坏"):
        prepare_image_bytes(file_id="one", name="sample.png", declared_mime="image/png", raw=b"not an image")


def test_normalize_generated_image_is_real_png() -> None:
    raw, width, height = normalize_generated_png(_image_bytes("JPEG"))
    assert raw.startswith(b"\x89PNG")
    assert (width, height) == (12, 8)


def test_provider_vision_capability_is_explicit() -> None:
    provider = SimpleNamespace(config={"model_capabilities": {"vision": {"vision": True}}})
    assert provider_model_supports_vision(provider, "vision") is True
    assert provider_model_supports_vision(provider, "legacy") is False


def test_openai_chat_body_preserves_image_content_parts() -> None:
    provider = SimpleNamespace(provider_type="openai")
    parts = [
        {"type": "text", "text": "what is shown"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]
    body = llm_client._build_chat_body(
        provider, "vision", [{"role": "user", "content": parts}], "", None, None, None, False,
    )
    assert body["messages"][0]["content"] == parts


@pytest.mark.asyncio
async def test_generate_image_accepts_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    image = _image_bytes("PNG")
    provider = SimpleNamespace(
        id="provider-1", provider_type="openai", base_url="https://api.example/v1",
        timeout_seconds=30, api_key_encrypted="ignored",
    )

    async def fake_key(_provider):
        return "secret"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/generations"
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image).decode()}]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(llm_client, "get_decrypted_api_key", fake_key)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", fake_client)
    result = await llm_client.generate_image(
        provider, "image-model", prompt="draw", size="1024x1024",
    )
    assert result.raw == image
    assert result.model_served == "image-model"


@pytest.mark.asyncio
async def test_generate_image_rejects_download_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = SimpleNamespace(
        id="provider-1", provider_type="openai", base_url="https://api.example/v1",
        timeout_seconds=30, api_key_encrypted="ignored",
    )

    async def fake_key(_provider):
        return "secret"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example/image.png"}]})
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(llm_client, "get_decrypted_api_key", fake_key)
    monkeypatch.setattr(llm_client, "_assert_public_image_url", lambda _url: None)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", fake_client)
    with pytest.raises(RuntimeError, match="redirects are not allowed"):
        await llm_client.generate_image(provider, "image-model", prompt="draw", size="1024x1024")
