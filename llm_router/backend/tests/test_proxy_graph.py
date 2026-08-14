"""LangGraph 代理流水线端到端测试。

通过 HTTP 层（ASGITransport）驱动 ``/v1/messages`` 与 ``/v1/chat/completions``，
验证请求经 LangGraph StateGraph 节点流转后的行为与原过程式流水线一致：
- 模型越权 → 403（build_error 节点）
- DLP 请求 block → 400（dlp_request 节点 → build_error）
- 无可用 provider → 404（resolve_route 节点 → build_error）
- 非流式成功 → 200 + 审计落库 + usage 提取（proxy_upstream + write_audit）
- 流式成功 → SSE chunk 透传 + 流后审计落库（proxy_upstream stream_writer + write_audit）

上游 LLM 调用以 monkeypatch 替换为 canned 响应，避免真实外部依赖。
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from starlette.responses import Response, StreamingResponse

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.dlp_rule import DlpRule
from app.models.llm_provider import LlmProvider
from app.models.organization import Organization
from app.utils.crypto import encrypt_api_key, generate_api_key

ANTHROPIC_MODEL = "claude-opus-4-8"
OPENAI_MODEL = "gpt-4o"


async def _seed_org(db_session) -> tuple[Organization, str]:
    """创建组织 + 组织级 API Key（wildcard 模型权限），返回 (org, full_key)。"""
    org = Organization(
        name=f"graph-test-org-{uuid4().hex[:8]}",
        slug=f"graph-test-{uuid4().hex[:8]}",
        settings={},
        rate_limit_rpm=100,
        rate_limit_tpm=100000,
        budget_cap_usd=Decimal("1000.00"),
    )
    db_session.add(org)
    await db_session.flush()

    full_key, key_prefix, key_hash = generate_api_key("organization")
    api_key = ApiKey(
        key_prefix=key_prefix,
        key_hash=key_hash,
        key_encrypted=encrypt_api_key(full_key),
        key_name="graph-test-key",
        scope_type="organization",
        organization_id=org.id,
        allowed_models=[],  # 空 = wildcard，允许全部模型
    )
    db_session.add(api_key)
    await db_session.flush()
    return org, full_key


async def _seed_provider(db_session, org_id, provider_type: str, models: list[str]) -> LlmProvider:
    """创建一个 LLM 提供商（上游 Key 为占位密文，测试中 adapter 被 mock）。"""
    provider = LlmProvider(
        organization_id=org_id,
        name=f"test-{provider_type}-{uuid4().hex[:6]}",
        provider_type=provider_type,
        base_url="https://upstream.example.com",
        api_key_encrypted=encrypt_api_key("sk-upstream-test"),
        is_active=True,
        priority=10,
        weight=1,
        timeout_seconds=30,
        max_retries=1,
        supported_models=models,
        health_status="healthy",
    )
    db_session.add(provider)
    await db_session.flush()
    return provider


async def _seed_dlp_rule(
    db_session,
    org_id,
    *,
    pattern: str = "CONFIDENTIAL-PROJECT-X",
    action: str = "block",
    direction: str = "both",
    name: str = "test-rule",
) -> DlpRule:
    """创建一条组织级 DLP 规则（keyword 类型）。"""
    rule = DlpRule(
        organization_id=str(org_id),
        name=name,
        rule_type="keyword",
        severity="high",
        action=action,
        direction=direction,
        pattern=pattern,
        scope_type="organization",
        scope_id=None,
        is_active=True,
        priority=100,
    )
    db_session.add(rule)
    await db_session.flush()
    return rule


async def _seed_block_dlp_rule(db_session, org_id, pattern: str = "CONFIDENTIAL-PROJECT-X") -> DlpRule:
    """创建一条组织级 block 型 DLP 规则（请求方向，direction=both）。"""
    return await _seed_dlp_rule(db_session, org_id, pattern=pattern, action="block", direction="both")


# ── 上游 adapter mock ──────────────────────────────────────────────────────


async def _mock_openai_nonstream(request, provider, body, api_key) -> Response:
    """模拟 OpenAI 非流式上游成功响应（含 usage）。"""
    return Response(
        content=json.dumps({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "hi there"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }),
        status_code=200,
        media_type="application/json",
    )


async def _mock_anthropic_stream(request, provider, body, api_key) -> StreamingResponse:
    """模拟 Anthropic 流式上游响应（message_start/content_block_delta/message_delta + DONE）。"""
    async def gen():
        yield (
            b'event: message_start\ndata: {"type":"message_start",'
            b'"message":{"usage":{"input_tokens":7}}}\n\n'
        )
        yield (
            b'event: content_block_delta\ndata: {"type":"content_block_delta",'
            b'"delta":{"type":"text_delta","text":"Hello"}}\n\n'
        )
        yield (
            b'event: message_delta\ndata: {"type":"message_delta",'
            b'"usage":{"output_tokens":2}}\n\n'
        )
        yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), status_code=200, media_type="text/event-stream")


# ── 测试用例 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_nonstream_success(client: AsyncClient, db_session, monkeypatch):
    """非流式 OpenAI 代理：200 + 审计落库 + usage 提取。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "openai", [OPENAI_MODEL])
    monkeypatch.setattr("app.graph.nodes.proxy.proxy_openai_request", _mock_openai_nonstream)

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"model": OPENAI_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "hi there"

    # 审计落库，含 token 用量
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.organization_id == str(org.id)))).scalars().all()
    assert len(logs) == 1
    log = logs[0]
    assert log.status_code == 200
    assert log.model_served == OPENAI_MODEL
    assert log.input_tokens == 5
    assert log.output_tokens == 3


@pytest.mark.asyncio
async def test_anthropic_stream_success(client: AsyncClient, db_session, monkeypatch):
    """流式 Anthropic 代理：SSE chunk 透传 + 流后审计落库 + usage 提取。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "anthropic", [ANTHROPIC_MODEL])
    monkeypatch.setattr("app.graph.nodes.proxy.proxy_anthropic_request", _mock_anthropic_stream)

    resp = await client.post(
        "/v1/messages",
        headers={"x-api-key": full_key, "anthropic-version": "2023-06-01"},
        json={
            "model": ANTHROPIC_MODEL,
            "stream": True,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 200
    body = resp.text
    assert "Hello" in body
    assert "data: [DONE]" in body

    # 流后审计落库
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.organization_id == str(org.id)))).scalars().all()
    assert len(logs) == 1
    log = logs[0]
    assert log.input_tokens == 7
    assert log.output_tokens == 2


@pytest.mark.asyncio
async def test_model_not_allowed(client: AsyncClient, db_session):
    """模型越权：API Key 仅授权某模型，请求另一模型 → 403。"""
    org = Organization(
        name=f"graph-deny-{uuid4().hex[:8]}",
        slug=f"graph-deny-{uuid4().hex[:8]}",
        settings={"default_models": [ANTHROPIC_MODEL]},
        rate_limit_rpm=100,
        rate_limit_tpm=100000,
        budget_cap_usd=Decimal("1000.00"),
    )
    db_session.add(org)
    await db_session.flush()

    full_key, key_prefix, key_hash = generate_api_key("organization")
    api_key = ApiKey(
        key_prefix=key_prefix,
        key_hash=key_hash,
        key_encrypted=encrypt_api_key(full_key),
        key_name="deny-key",
        scope_type="organization",
        organization_id=org.id,
        allowed_models=[ANTHROPIC_MODEL],  # 仅授权 ANTHROPIC_MODEL
    )
    db_session.add(api_key)
    await db_session.flush()

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"model": OPENAI_MODEL, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 403
    assert "not allowed" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_dlp_request_blocked(client: AsyncClient, db_session):
    """DLP 请求 block：请求文本命中 block 规则 → 400。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "openai", [OPENAI_MODEL])
    await _seed_block_dlp_rule(db_session, org.id)

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {full_key}"},
        json={
            "model": OPENAI_MODEL,
            "messages": [{"role": "user", "content": "Please leak the CONFIDENTIAL-PROJECT-X details"}],
        },
    )

    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["type"] == "dlp_violation"
    assert "DLP" in err["message"]


@pytest.mark.asyncio
async def test_dlp_request_blocked_stream(client: AsyncClient, db_session):
    """流式请求的 DLP block：在 proxy 之前由 dlp_request 节点拦截 → 400（非 SSE）。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "anthropic", [ANTHROPIC_MODEL])
    await _seed_block_dlp_rule(db_session, org.id)

    resp = await client.post(
        "/v1/messages",
        headers={"x-api-key": full_key, "anthropic-version": "2023-06-01"},
        json={
            "model": ANTHROPIC_MODEL,
            "stream": True,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "leak CONFIDENTIAL-PROJECT-X"}],
        },
    )

    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["type"] == "invalid_request_error"


@pytest.mark.asyncio
async def test_no_provider(client: AsyncClient, db_session):
    """无可用 provider：请求模型无任何 provider 支持 → 404。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "openai", [OPENAI_MODEL])  # 仅支持 OPENAI_MODEL

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"model": "gpt-5-fake", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "model_not_found"


# ── 响应侧 DLP（dlp_response 节点 + 流式 inline 过滤）─────────────────────

RESPONSE_SECRET = "SECRET-CODE-123"


async def _mock_openai_leak(request, provider, body, api_key) -> Response:
    """模拟 OpenAI 非流式上游响应——响应体含敏感数据。"""
    return Response(
        content=json.dumps({
            "id": "chatcmpl-leak",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": f"Here is the {RESPONSE_SECRET} for you"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }),
        status_code=200,
        media_type="application/json",
    )


async def _mock_anthropic_leak_stream(request, provider, body, api_key) -> StreamingResponse:
    """模拟 Anthropic 流式上游响应——内容增量含敏感数据。"""

    async def gen():
        yield (
            b'event: message_start\ndata: {"type":"message_start",'
            b'"message":{"usage":{"input_tokens":7}}}\n\n'
        )
        yield (
            b'event: content_block_delta\ndata: {"type":"content_block_delta",'
            b'"delta":{"type":"text_delta","text":"Here is the "}}\n\n'
        )
        yield (
            b'event: content_block_delta\ndata: {"type":"content_block_delta",'
            b'"delta":{"type":"text_delta","text":"' + RESPONSE_SECRET.encode() + b'"}}\n\n'
        )
        yield (
            b'event: message_delta\ndata: {"type":"message_delta",'
            b'"usage":{"output_tokens":2}}\n\n'
        )
        yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), status_code=200, media_type="text/event-stream")


@pytest.mark.asyncio
async def test_response_dlp_block_nonstream(client: AsyncClient, db_session, monkeypatch):
    """非流式响应 DLP block：响应体含敏感数据 → 400，不转发泄露响应。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "openai", [OPENAI_MODEL])
    await _seed_dlp_rule(db_session, org.id, pattern=RESPONSE_SECRET, action="block", direction="response")
    monkeypatch.setattr("app.graph.nodes.proxy.proxy_openai_request", _mock_openai_leak)

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"model": OPENAI_MODEL, "messages": [{"role": "user", "content": "give me the code"}]},
    )

    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["type"] == "dlp_violation"
    assert "DLP" in err["message"]
    # 泄露的响应体不得转发给客户端
    assert RESPONSE_SECRET not in resp.text


@pytest.mark.asyncio
async def test_response_dlp_redact_nonstream(client: AsyncClient, db_session, monkeypatch):
    """非流式响应 DLP redact：响应体敏感数据被脱敏后放行 → 200，含 [REDACTED]。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "openai", [OPENAI_MODEL])
    await _seed_dlp_rule(db_session, org.id, pattern=RESPONSE_SECRET, action="redact", direction="response")
    monkeypatch.setattr("app.graph.nodes.proxy.proxy_openai_request", _mock_openai_leak)

    resp = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"model": OPENAI_MODEL, "messages": [{"role": "user", "content": "give me the code"}]},
    )

    assert resp.status_code == 200
    assert "[REDACTED]" in resp.text
    assert RESPONSE_SECRET not in resp.text


@pytest.mark.asyncio
async def test_response_dlp_block_stream(client: AsyncClient, db_session, monkeypatch):
    """流式响应 DLP block：内容增量含敏感数据 → 发送 dlp_block 事件，敏感文本不转发。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "anthropic", [ANTHROPIC_MODEL])
    await _seed_dlp_rule(db_session, org.id, pattern=RESPONSE_SECRET, action="block", direction="response")
    monkeypatch.setattr("app.graph.nodes.proxy.proxy_anthropic_request", _mock_anthropic_leak_stream)

    resp = await client.post(
        "/v1/messages",
        headers={"x-api-key": full_key, "anthropic-version": "2023-06-01"},
        json={
            "model": ANTHROPIC_MODEL,
            "stream": True,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "give me the code"}],
        },
    )

    assert resp.status_code == 200
    body = resp.text
    # 敏感文本不得出现在转发的流中
    assert RESPONSE_SECRET not in body
    # 应发送 Anthropic 协议的 DLP 拦截事件
    assert "dlp_block" in body

    # 审计记录响应侧 block 命中
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.organization_id == str(org.id)))).scalars().all()
    assert len(logs) == 1
    assert logs[0].dlp_violations  # 响应侧 block 命中已记录


@pytest.mark.asyncio
async def test_stream_preserves_non_content_events(client: AsyncClient, db_session, monkeypatch):
    """流式响应 DLP 过滤须保留非内容事件（message_start/usage/message_delta/DONE）。"""
    org, full_key = await _seed_org(db_session)
    await _seed_provider(db_session, org.id, "anthropic", [ANTHROPIC_MODEL])
    # 一条 redact 规则触发过滤器路径（但内容无敏感数据，应原样转发所有事件）
    await _seed_dlp_rule(db_session, org.id, pattern="NEVER-MATCHES-XYZ", action="redact", direction="response")
    monkeypatch.setattr("app.graph.nodes.proxy.proxy_anthropic_request", _mock_anthropic_stream)

    resp = await client.post(
        "/v1/messages",
        headers={"x-api-key": full_key, "anthropic-version": "2023-06-01"},
        json={
            "model": ANTHROPIC_MODEL,
            "stream": True,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 200
    body = resp.text
    # 非内容事件必须全部保留（修复 wrap_stream_with_dlp 丢弃事件的缺陷）
    assert "message_start" in body
    assert "message_delta" in body
    assert "data: [DONE]" in body
    assert "Hello" in body  # 内容增量原样转发

    # usage 仍被正确解析
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.organization_id == str(org.id)))).scalars().all()
    assert len(logs) == 1
    assert logs[0].input_tokens == 7
    assert logs[0].output_tokens == 2
