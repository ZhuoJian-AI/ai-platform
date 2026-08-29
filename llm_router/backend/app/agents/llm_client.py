"""Org-scoped LLM client for the agent runtime.

复用模型路由器的 provider 解析、密钥解密与协议适配能力，但**不走** /v1 HTTP 代理端点：
直接用解析后的 provider + 解密 key 经 httpx 调上游 chat / embeddings。这样 agent 运行时
与 RAG 嵌入共享同一套 org 作用域模型解析，且无需自建 API Key 调用本机代理。

- ``chat``  / ``stream_chat``：消息 → assistant 文本 + tool_calls + usage（OpenAI/Anthropic 双协议）
- ``embed``：文本列表 → 嵌入向量列表（OpenAI 兼容 /embeddings 端点）

密钥仅在函数内按 provider 解密、就地使用，绝不返回或入 graph state（参照 ProxyState 约定）。
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_provider import LlmProvider
from app.routing.router import find_provider
from app.services.llm_provider_service import get_decrypted_api_key

logger = structlog.get_logger()

ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class LlmResult:
    content: str
    tool_calls: list[dict]  # OpenAI 风格: [{"id","name","arguments":<json-str>}]
    usage: dict  # {"input_tokens": int|None, "output_tokens": int|None}
    provider_id: str
    model_served: str


@dataclass
class ImageGenerationResult:
    raw: bytes
    provider_id: str
    model_served: str
    revised_prompt: str | None = None


async def _resolve(
    db: AsyncSession, org_id: UUID, model_alias: str, *, for_embeddings: bool = False,
    dept_id: str | UUID | None = None, team_id: str | UUID | None = None,
) -> tuple[LlmProvider, str]:
    """选 provider。model_alias 为真实模型 id（或 "default" 走组织默认路由）。返回 (provider, model)。

    dept_id/team_id 取自智能体运行时作用域，用于按 团队>部门>组织 优先级筛选继承 provider。
    """
    model = model_alias
    preferred = "openai" if for_embeddings else None
    provider = await find_provider(db, org_id, model, preferred_type=preferred, dept_id=dept_id, team_id=team_id)
    if provider is None:
        raise RuntimeError(f"no provider available for model '{model}' in org {org_id}")
    return provider, model


async def resolve_provider_model(
    db: AsyncSession, org_id: UUID, model_alias: str, *, for_embeddings: bool = False,
    dept_id: str | UUID | None = None, team_id: str | UUID | None = None,
) -> tuple[str, str]:
    """公开封装：model_alias→(provider_id, model)。

    供审计/监控按 provider 归属智能体通路的 LLM 用量（agent 运行时直连上游、不经 /v1 代理
    端点，故需在落审计日志时显式解析 provider，否则 by_provider 维度会落空）。
    """
    provider, actual_model = await _resolve(
        db, org_id, model_alias, for_embeddings=for_embeddings, dept_id=dept_id, team_id=team_id,
    )
    return str(provider.id), actual_model


async def resolve_provider(
    db: AsyncSession, org_id: UUID, model_alias: str, *,
    dept_id: str | UUID | None = None, team_id: str | UUID | None = None,
) -> tuple[LlmProvider, str]:
    """Resolve a concrete provider once so a multimodal turn cannot switch protocols mid-loop."""
    return await _resolve(db, org_id, model_alias, dept_id=dept_id, team_id=team_id)


def _auth_headers(provider: LlmProvider, api_key: str) -> dict[str, str]:
    if provider.provider_type == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    # openai / azure_openai / custom：Bearer
    return {"authorization": f"Bearer {api_key}", "content-type": "application/json"}


def _chat_url(provider: LlmProvider) -> str:
    """上游 chat 端点。

    约定（与代理层 ``app.proxy.openai_adapter`` 一致）：
    - OpenAI 兼容 provider 的 ``base_url`` **已含 ``/v1``**（如
      ``https://.../compatible-mode/v1``），故只补 ``/chat/completions``；
      若再补 ``/v1`` 会产生 ``.../v1/v1/chat/completions`` 双重路径，
      被上游（阿里云百炼/MaaS）以 ``url error, please check url!`` 拒绝。
    - Anthropic 的 ``base_url`` **不含 ``/v1``**，补 ``/v1/messages``。
    """
    base = provider.base_url.rstrip("/")
    if provider.provider_type == "anthropic":
        return f"{base}/v1/messages"
    return f"{base}/chat/completions"


def _embed_url(provider: LlmProvider) -> str:
    """上游 embeddings 端点（OpenAI 兼容；base_url 已含 ``/v1``，只补 ``/embeddings``）。"""
    return f"{provider.base_url.rstrip('/')}/embeddings"


def _images_url(provider: LlmProvider, endpoint_path: str) -> str:
    path = endpoint_path.strip()
    if not path.startswith("/") or "://" in path or ".." in path:
        raise RuntimeError("invalid image generation endpoint_path")
    return f"{provider.base_url.rstrip('/')}{path}"


def _assert_public_image_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("image generation returned an invalid URL")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise RuntimeError("image generation URL cannot be resolved") from exc
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            raise RuntimeError("image generation URL points to a private or reserved address")


_THINKING_DISABLED_MODELS = frozenset(
    m.strip() for m in os.getenv("CHAT_THINKING_DISABLED_MODELS", "").split(",") if m.strip()
)


def _build_chat_body(
    provider: LlmProvider,
    model: str,
    messages: list[dict],
    system_prompt: str,
    temperature: float | None,
    max_tokens: int | None,
    tools: list[dict] | None,
    stream: bool,
) -> dict:
    """按 provider 协议构造 chat 请求体。messages 为 OpenAI 风格 [{role, content, tool_calls?}]。"""
    if provider.provider_type == "anthropic":
        # Anthropic: system 单独，messages 仅 user/assistant
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or 4096,
            "messages": _to_anthropic_messages(messages),
        }
        if system_prompt:
            body["system"] = system_prompt
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = [
                {"name": t["function"]["name"], "description": t["function"].get("description", ""),
                 "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}})}
                for t in tools
            ]
        if stream:
            body["stream"] = True
        return body

    # OpenAI 风格
    body = {
        "model": model,
        "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages,
    }
    # 推理模型的思考期是纯等待（DeepSeek v4 系先想数秒再吐字）。对延迟敏感的
    # 部署可按模型显式关掉：CHAT_THINKING_DISABLED_MODELS=deepseek-v4-flash,...
    # 默认为空，不改变任何现有行为。仅 OpenAI 风格通道生效。
    if model in _THINKING_DISABLED_MODELS:
        body["thinking"] = {"type": "disabled"}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools:
        body["tools"] = tools
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    return body


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """把 OpenAI 风格消息序列转为 Anthropic 风格（合并 tool 角色为 tool_result）。"""
    out: list[dict] = []
    for m in messages:
        role = m["role"]
        if role == "tool":
            # OpenAI tool 结果 → Anthropic user/tool_result
            out.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m.get("content", "")}
            ]})
        elif role == "assistant" and m.get("tool_calls"):
            content: list[dict] = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m["tool_calls"]:
                content.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                                "input": _safe_json(tc["function"].get("arguments", "{}"))})
            out.append({"role": "assistant", "content": content})
        else:
            out.append({"role": role, "content": _to_anthropic_content(m.get("content", ""))})
    return out


def _to_anthropic_content(content: Any) -> Any:
    """Convert OpenAI multimodal content blocks to Anthropic Messages blocks."""
    if not isinstance(content, list):
        return content
    converted: list[dict] = []
    for part in content:
        if not isinstance(part, dict):
            raise RuntimeError("invalid multimodal message content")
        if part.get("type") == "text":
            converted.append({"type": "text", "text": str(part.get("text", ""))})
            continue
        if part.get("type") != "image_url":
            converted.append(part)
            continue
        image_url = part.get("image_url") or {}
        url = str(image_url.get("url") or "")
        if url.startswith("data:"):
            header, separator, encoded = url.partition(",")
            media_type = header[5:].split(";", 1)[0].lower()
            if separator != "," or ";base64" not in header.lower():
                raise RuntimeError("Anthropic image data URL must use base64 encoding")
            if media_type == "image/jpg":
                media_type = "image/jpeg"
            if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
                raise RuntimeError("Anthropic image type is not supported")
            try:
                base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("Anthropic image data is not valid base64") from exc
            converted.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": encoded},
            })
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError("Anthropic image URL is invalid")
        converted.append({"type": "image", "source": {"type": "url", "url": url}})
    return converted


def _safe_json(s: str) -> Any:
    try:
        return json.loads(s) if isinstance(s, str) else s
    except (json.JSONDecodeError, TypeError):
        return {}


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
    """非流式 chat。返回 assistant 文本 + tool_calls + usage。"""
    if provider_override is not None:
        provider, model = provider_override, (model_override or model_alias)
    else:
        provider, model = await _resolve(db, org_id, model_alias, dept_id=dept_id, team_id=team_id)
    api_key = await get_decrypted_api_key(provider)
    body = _build_chat_body(provider, model, messages, system_prompt, temperature, max_tokens, tools, stream=False)

    async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
        resp = await client.post(_chat_url(provider), headers=_auth_headers(provider, api_key), json=body)
    data = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream chat error {resp.status_code}: {data}")

    if provider.provider_type == "anthropic":
        content_parts = data.get("content", [])
        text = "".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
        tool_calls = [
            {"id": p["id"], "name": p["name"], "arguments": json.dumps(p.get("input", {}))}
            for p in content_parts if p.get("type") == "tool_use"
        ]
        u = data.get("usage", {})
        usage = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
    else:
        choice = (data.get("choices") or [{}])[0].get("message", {})
        text = choice.get("content") or ""
        tool_calls = []
        for tc in choice.get("tool_calls") or []:
            fn = tc.get("function", {})
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments", ""),
            })
        u = data.get("usage", {})
        usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}

    return LlmResult(content=text, tool_calls=tool_calls, usage=usage, provider_id=str(provider.id), model_served=model)


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
    """流式 chat，yield (event, payload, extra)。

    - ("text", delta_str, None)                       逐 token 文本，实时下发
    - ("tool_calls", [OpenAI 风格 tool_call], None)    本轮流式累积的完整工具调用，流末一次性下发
    - ("usage", None, {"input_tokens","output_tokens"})
    """
    if provider_override is not None:
        provider, model = provider_override, (model_override or model_alias)
    else:
        provider, model = await _resolve(db, org_id, model_alias, dept_id=dept_id, team_id=team_id)
    api_key = await get_decrypted_api_key(provider)
    body = _build_chat_body(provider, model, messages, system_prompt, temperature, max_tokens, tools, stream=True)
    is_anthropic = provider.provider_type == "anthropic"

    # 工具调用累积器
    # OpenAI 兼容: {index: {"id","name","arguments"}}
    oai_tc: dict[int, dict] = {}
    # Anthropic: {block_index: {"id","name","json_acc"}}
    ant_blocks: dict[int, dict] = {}

    async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
        async with client.stream(
            "POST", _chat_url(provider),
            headers=_auth_headers(provider, api_key), json=body,
        ) as resp:
            if resp.status_code >= 400:
                err = await resp.aread()
                raise RuntimeError(f"upstream stream error {resp.status_code}: {err.decode(errors='replace')}")

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                if is_anthropic:
                    etype = data.get("type")
                    if etype == "content_block_delta":
                        d = data.get("delta", {})
                        if d.get("type") == "text_delta":
                            yield ("text", d.get("text", ""), None)
                        elif d.get("type") == "input_json_delta":
                            idx = (data.get("index") if data.get("index") is not None
                                   else max(ant_blocks) if ant_blocks else 0)
                            blk = ant_blocks.setdefault(idx, {"id": "", "name": "", "json_acc": ""})
                            blk["json_acc"] += d.get("partial_json", "")
                    elif etype == "content_block_start":
                        blk = (data.get("content_block") or {})
                        if blk.get("type") == "tool_use":
                            ant_blocks[data.get("index", 0)] = {
                                "id": blk.get("id", ""),
                                "name": blk.get("name", ""),
                                "json_acc": "",
                            }
                    elif etype == "content_block_stop":
                        idx = data.get("index")
                        if idx in ant_blocks:
                            blk = ant_blocks[idx]
                            try:
                                parsed = json.loads(blk["json_acc"]) if blk["json_acc"] else {}
                            except json.JSONDecodeError:
                                parsed = _safe_json(blk["json_acc"])
                            blk["input"] = parsed
                    elif etype == "message_start":
                        u = (data.get("message") or {}).get("usage") or {}
                        yield ("usage", None, {"input_tokens": u.get("input_tokens"), "output_tokens": None})
                    elif etype == "message_delta":
                        u = data.get("usage") or {}
                        yield ("usage", None, {"input_tokens": None, "output_tokens": u.get("output_tokens")})
                else:
                    for choice in data.get("choices", []) or []:
                        delta = choice.get("delta", {})
                        if delta.get("content"):
                            yield ("text", delta["content"], None)
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            slot = oai_tc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
                    if data.get("usage"):
                        u = data["usage"]
                        yield ("usage", None, {
                            "input_tokens": u.get("prompt_tokens"),
                            "output_tokens": u.get("completion_tokens"),
                        })

    # 流末下发本轮累积的完整 tool_calls（OpenAI 风格 [{"id","name","arguments":json-str}]）
    if is_anthropic:
        tool_calls = [
            {"id": b["id"], "name": b["name"], "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}
            for b in ant_blocks.values()
        ]
    else:
        tool_calls = [
            {"id": s["id"], "name": s["name"], "arguments": s["arguments"]}
            for _, s in sorted(oai_tc.items())
        ]
    if tool_calls:
        yield ("tool_calls", tool_calls, None)


async def generate_image(
    provider: LlmProvider, model: str, *, prompt: str, size: str,
    quality: str | None = None, endpoint_path: str = "/images/generations",
    max_bytes: int = 5 * 1024 * 1024,
) -> ImageGenerationResult:
    """Call an OpenAI-compatible Images API and accept either b64_json or a temporary URL."""
    if provider.provider_type == "anthropic":
        raise RuntimeError("Anthropic provider is not supported by the image generation adapter")
    api_key = await get_decrypted_api_key(provider)
    body: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1, "size": size}
    if quality:
        body["quality"] = quality
    # Do not follow redirects when downloading a provider-supplied URL.  The
    # original URL is checked for public routing below, but a redirect could
    # otherwise bounce the request into a private network.
    async with httpx.AsyncClient(timeout=provider.timeout_seconds, follow_redirects=False) as client:
        response = await client.post(
            _images_url(provider, endpoint_path), headers=_auth_headers(provider, api_key), json=body,
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"upstream image error {response.status_code}: invalid JSON") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"upstream image error {response.status_code}: {data}")
        item = (data.get("data") or [{}])[0]
        raw: bytes
        if item.get("b64_json"):
            try:
                raw = base64.b64decode(item["b64_json"], validate=True)
            except (ValueError, TypeError) as exc:
                raise RuntimeError("image generation returned invalid base64") from exc
        elif item.get("url"):
            _assert_public_image_url(str(item["url"]))
            async with client.stream("GET", str(item["url"])) as image_response:
                if 300 <= image_response.status_code < 400:
                    raise RuntimeError("generated image download redirects are not allowed")
                if image_response.status_code >= 400:
                    raise RuntimeError(f"generated image download failed ({image_response.status_code})")
                chunks: list[bytes] = []
                total = 0
                async for chunk in image_response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError("generated image exceeds the 5MB limit")
                    chunks.append(chunk)
                raw = b"".join(chunks)
        else:
            raise RuntimeError("image generation returned neither b64_json nor url")
    if not raw or len(raw) > max_bytes:
        raise RuntimeError("generated image is empty or exceeds the 5MB limit")
    return ImageGenerationResult(
        raw=raw, provider_id=str(provider.id), model_served=model,
        revised_prompt=item.get("revised_prompt"),
    )


async def embed(
    db: AsyncSession,
    org_id: UUID,
    model: str,
    texts: list[str],
    *,
    dept_id: str | UUID | None = None,
    team_id: str | UUID | None = None,
    provider_override: LlmProvider | None = None,
    model_override: str | None = None,
) -> list[list[float]]:
    """文本嵌入（OpenAI 兼容 /v1/embeddings）。返回与 texts 等长的向量列表。"""
    if provider_override is not None:
        provider, actual = provider_override, (model_override or model)
    else:
        provider, actual = await _resolve(
            db, org_id, model, for_embeddings=True, dept_id=dept_id, team_id=team_id,
        )
    if provider.provider_type == "anthropic":
        raise RuntimeError("Anthropic provider does not expose embeddings; configure an OpenAI-compatible provider")
    api_key = await get_decrypted_api_key(provider)
    headers = _auth_headers(provider, api_key)
    async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
        resp = await client.post(_embed_url(provider), headers=headers,
                                 json={"model": actual, "input": texts})
    data = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream embed error {resp.status_code}: {data}")
    return [item["embedding"] for item in sorted(data.get("data", []), key=lambda x: x.get("index", 0))]
